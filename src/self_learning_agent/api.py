"""HTTP API:把同一张教学图包成可被其他系统调用的服务(ADR-0004 / #011)。

产品形态 = **被其他系统调用的 API**,不是终端用户应用。本模块与 ``cli.py`` 是
同一张图的**两个薄驱动器**:对话端点复用 ``runner.invoke_turn``(同一张图、同一
控制流,无业务逻辑分叉),其余端点复用 ``workspace`` 的确定性文件原语。

身份由调用方提供并被**直接信任**:智能体永不自管账号 / 鉴权 / 计费;多租户仅靠
调用方传入的 ``user_id`` / ``topic``——它们经 ``tenancy`` 收敛成工作区目录与
``thread_id``,天然隔离(ADR-0003/0004)。"开浏览器看课"是 CLI 专属便利,API 没有。

能力面(PRD「API 能力面」/ 本 issue 验收):
1. **对话**:``POST /chat``  发 ``(user_id, topic)`` 消息 → 回复 + 本轮产物引用。
2. **取产物**:``GET /artifacts`` 列出 + ``GET /artifacts/content`` 下载课程 / 参考 /
   词汇表 / 使命 / 学习记录 / 资源 / 资产。
3. **查状态/进度**(只读):``GET /status`` 当前 Mission、已有课程、学习记录。
4. **删除/重置工作区**(必须):``DELETE /workspace`` 严格限定在该 ``(user_id, topic)``
   命名空间。
5. **导出工作区**(应有):``GET /export`` 打包整个工作区为 zip,供备份 / 迁移 /
   让学习者带走自己的数据。

图实例经 FastAPI 依赖 ``get_api_graph`` 注入,默认走进程级单例(SQLite checkpointer);
API 层缝测试通过 ``app.dependency_overrides`` 注入 MemorySaver 图,保持 hermetic。
"""

from __future__ import annotations

import io
import mimetypes
import shutil
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import graph as graph_module
from . import workspace
from .runner import invoke_turn
from .tenancy import topic_slug

# === 产物分类 =================================================================
# 把工作区里的相对路径归类成对调用方有意义的产物类型(供其在自己的界面里分区渲染)。
# 分类只看路径前缀 / 文件名,纯确定性,与 workspace.py 的目录约定一一对应。
_LESSONS_DIR = "lessons/"
_REFERENCE_DIR = "reference/"
_ASSETS_DIR = "assets/"
_LEARNING_RECORDS_DIR = "learning-records/"


def _artifact_kind(relative: str) -> str:
    """把一个产物相对路径归类(lesson / reference / glossary / mission / record / …)。"""
    if relative == "MISSION.md":
        return "mission"
    if relative == "GLOSSARY.md":
        return "glossary"
    if relative == "RESOURCES.md":
        return "resources"
    if relative.startswith(_LESSONS_DIR):
        return "lessons_index" if relative.endswith("index.html") else "lesson"
    if relative.startswith(_REFERENCE_DIR):
        return "reference_index" if relative.endswith("index.html") else "reference"
    if relative.startswith(_ASSETS_DIR):
        return "asset"
    if relative.startswith(_LEARNING_RECORDS_DIR):
        return "learning_record"
    return "other"


# === 请求 / 响应模型 ==========================================================
class ChatRequest(BaseModel):
    """一条学习者消息 + 其归属的多租户键。"""

    user_id: str = Field(..., description="学习者 ID(由调用方提供,被直接信任)")
    topic: str = Field(..., description="学习主题(自由文本)")
    message: str = Field(..., description="学习者这一轮说的话")


class ChatResponse(BaseModel):
    """一轮交互的外部可见结果(对应 ``runner.TurnResult``)。"""

    reply: str
    new_artifacts: list[str] = Field(
        default_factory=list, description="本轮新产出 / 改动的产物相对路径"
    )
    awaiting_input: bool = Field(
        default=False, description="图是否停在 interrupt 上、等待学习者继续作答"
    )
    spawn_topic: str | None = Field(
        default=None,
        description="非空表示本轮交接到新主题:reply 已是新主题的首响应,调用方后续请用此 topic",
    )


class ArtifactInfo(BaseModel):
    """产物清单里的一条(相对路径 + 归类 + 字节数)。"""

    path: str
    kind: str
    bytes: int


class ArtifactList(BaseModel):
    """某 ``(user_id, topic)`` 的全部产物清单。"""

    user_id: str
    topic: str
    topic_slug: str
    artifacts: list[ArtifactInfo] = Field(default_factory=list)


class StatusResponse(BaseModel):
    """只读状态/进度:当前 Mission、已有课程、学习记录。"""

    user_id: str
    topic: str
    topic_slug: str
    exists: bool = Field(..., description="该工作区是否已存在任何产物")
    mission: str | None = Field(None, description="MISSION.md 全文,未立则为 null")
    has_resources: bool = Field(..., description="RESOURCES.md 是否已备")
    lessons: list[str] = Field(default_factory=list, description="已有课程文件相对路径")
    learning_records: list[str] = Field(
        default_factory=list, description="已有学习记录文件相对路径"
    )


class ResetResponse(BaseModel):
    """删除/重置工作区的结果。"""

    user_id: str
    topic: str
    topic_slug: str
    deleted: bool = Field(..., description="是否删除了已存在的工作区(本就不存在则 false)")


# === 图依赖(可注入)==========================================================
def get_api_graph():
    """返回对话端点用的图实例。默认进程级单例(SQLite);测试经 ``dependency_overrides``
    注入 MemorySaver 图以保持 hermetic。"""
    return graph_module.get_graph()


# === 文件定位 + 安全 ==========================================================
def _resolved_workspace(user_id: str, topic: str) -> tuple[Path, str]:
    """据 ``(user_id, topic)`` 算出工作区目录(已 resolve)与 ``topic_slug``。"""
    slug = topic_slug(topic)
    return workspace.workspace_dir(user_id, slug).resolve(), slug


def _safe_target(directory: Path, relative: str) -> Path:
    """把一个调用方给的相对路径安全地落在工作区内,挡掉路径穿越(``../`` 逃逸)。

    单一事实源是工作区目录;任何下载/读取都必须证明目标仍在该目录之内,否则视为
    越权访问(返回 400),绝不让 ``..`` / 绝对路径读到工作区之外的文件。
    """
    if not relative or relative.startswith("/") or "\x00" in relative:
        raise HTTPException(status_code=400, detail="invalid artifact path")
    target = (directory / relative).resolve()
    if target != directory and directory not in target.parents:
        raise HTTPException(status_code=400, detail="artifact path escapes workspace")
    return target


# === 应用装配 =================================================================
def create_app() -> FastAPI:
    """装配 FastAPI 应用。``uvicorn self_learning_agent.api:app`` 用模块级 ``app``;
    测试用本工厂造独立实例并注入图依赖。"""
    app = FastAPI(
        title="Self-Learning Agent API",
        description="承接 teach skill 的独立教学智能体;身份由调用方提供,本服务不做鉴权。",
        version="0.1.0",
    )

    @app.post("/chat", response_model=ChatResponse)
    def chat(req: ChatRequest, graph=Depends(get_api_graph)) -> ChatResponse:
        """对话:发一条学习者消息 → 取回复 + 本轮产物引用。

        复用 ``runner.invoke_turn``——与 CLI 完全同一张图、同一控制流(有未决
        interrupt 则 resume,否则 Router 分类),API 不引入任何业务逻辑分叉。
        """
        result = invoke_turn(req.user_id, req.topic, req.message, graph=graph)
        # new_topic 交接(#014 / §D4):agent 确认领域外新主题后返回 spawn_topic;driver
        # 立即用新 topic 另起一次 invoke(新 thread / 新记忆),把学习者续到新主题的使命访谈,
        # 并在响应里带回 spawn_topic 让调用方后续都用新 topic(服务端自动续上,一次逻辑交互)。
        if result.spawn_topic:
            handoff = invoke_turn(
                req.user_id, result.spawn_topic, f"我想学{result.spawn_topic}", graph=graph
            )
            return ChatResponse(
                reply=handoff.reply,
                new_artifacts=list(handoff.new_artifacts),
                awaiting_input=handoff.awaiting_input,
                spawn_topic=result.spawn_topic,
            )
        return ChatResponse(
            reply=result.reply,
            new_artifacts=list(result.new_artifacts),
            awaiting_input=result.awaiting_input,
        )

    @app.get("/artifacts", response_model=ArtifactList)
    def list_artifacts(
        user_id: str = Query(...), topic: str = Query(...)
    ) -> ArtifactList:
        """列出某学习者某主题下的全部产物(课程 / 参考 / 词汇表 / 使命 / 记录 / 资源 / 资产)。"""
        directory, slug = _resolved_workspace(user_id, topic)
        snapshot = workspace.scan_files(directory)
        artifacts = [
            ArtifactInfo(
                path=relative,
                kind=_artifact_kind(relative),
                bytes=(directory / relative).stat().st_size,
            )
            for relative in sorted(snapshot)
        ]
        return ArtifactList(
            user_id=user_id, topic=topic, topic_slug=slug, artifacts=artifacts
        )

    @app.get("/artifacts/content")
    def download_artifact(
        user_id: str = Query(...),
        topic: str = Query(...),
        path: str = Query(..., description="产物相对路径(来自 /artifacts 清单)"),
    ) -> Response:
        """下载单个产物的原始字节(供调用方在自己的界面里渲染课程 HTML 等)。"""
        directory, _ = _resolved_workspace(user_id, topic)
        target = _safe_target(directory, path)
        if not target.is_file():
            raise HTTPException(status_code=404, detail="artifact not found")
        media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        return Response(content=target.read_bytes(), media_type=media_type)

    @app.get("/status", response_model=StatusResponse)
    def status(user_id: str = Query(...), topic: str = Query(...)) -> StatusResponse:
        """只读状态/进度:当前 Mission、已有课程、学习记录(供调用方展示学习进展)。"""
        directory, slug = _resolved_workspace(user_id, topic)
        snapshot = workspace.scan_files(directory)
        lessons = sorted(
            rel
            for rel in snapshot
            if rel.startswith(_LESSONS_DIR) and not rel.endswith("index.html")
        )
        records = sorted(
            rel for rel in snapshot if rel.startswith(_LEARNING_RECORDS_DIR)
        )
        return StatusResponse(
            user_id=user_id,
            topic=topic,
            topic_slug=slug,
            exists=bool(snapshot),
            mission=workspace.read_text(directory, "MISSION.md"),
            has_resources=workspace.exists(directory, "RESOURCES.md"),
            lessons=lessons,
            learning_records=records,
        )

    @app.delete("/workspace", response_model=ResetResponse)
    def reset_workspace(
        user_id: str = Query(...), topic: str = Query(...)
    ) -> ResetResponse:
        """删除/重置某工作区(退课 / 毕业 / 数据删除 / 重新学习)。

        **严格限定在该 ``(user_id, topic_slug)`` 命名空间**:只 rmtree 这一个工作区
        目录,绝不触及别的学习者 / 主题(多租户隔离的强约束,见验收 4 与图层缝测试)。
        会话/图状态(checkpointer)的清理由调用方按需另行处理;本端点删的是 B/C 层
        文件这一单一事实源。
        """
        directory, slug = _resolved_workspace(user_id, topic)
        existed = directory.exists()
        if existed:
            shutil.rmtree(directory)
        return ResetResponse(
            user_id=user_id, topic=topic, topic_slug=slug, deleted=existed
        )

    @app.get("/export")
    def export_workspace(
        user_id: str = Query(...), topic: str = Query(...)
    ) -> Response:
        """导出整个工作区为 zip(备份 / 迁移 / 让学习者带走自己的数据)。"""
        directory, slug = _resolved_workspace(user_id, topic)
        if not directory.exists():
            raise HTTPException(status_code=404, detail="workspace not found")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for relative in sorted(workspace.scan_files(directory)):
                archive.write(directory / relative, arcname=relative)
        # slug 可能含中文,直接进 latin-1 的 HTTP 头会炸;按 RFC 5987 用
        # ``filename*=UTF-8''…`` 携带 UTF-8 文件名,并给一个纯 ASCII 兜底 filename。
        encoded = quote(f"{slug}.zip", safe="")
        headers = {
            "Content-Disposition": (
                f'attachment; filename="workspace.zip"; filename*=UTF-8\'\'{encoded}'
            )
        }
        return Response(
            content=buffer.getvalue(), media_type="application/zip", headers=headers
        )

    return app


app = create_app()
