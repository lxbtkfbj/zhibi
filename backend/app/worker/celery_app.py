from celery import Celery

import app  # noqa: F401  Windows 事件循环设置
from app.config import get_settings

settings = get_settings()

celery_app = Celery("zhibi", broker=settings.redis_url, include=["app.worker.tasks"])
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
    # 长篇任务可能跑很久；任务锁保证同一任务不会被两个 worker 同时执行
    broker_transport_options={"visibility_timeout": 6 * 3600},
    task_default_queue="zhibi",
)
