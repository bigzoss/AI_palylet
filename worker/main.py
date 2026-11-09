import logging
import signal
import threading
from datetime import datetime, timedelta, timezone

from openai import APIStatusError, AuthenticationError, PermissionDeniedError, RateLimitError
from sqlalchemy import select, update

from backend.db import Job, Session, init_db, now
from backend.services.gateway import ConfigurationError, UncertainRequest
from backend.workflows import Cancelled, Workflow

logger = logging.getLogger("worker")
stopping = threading.Event()


def claim():
    with Session() as db:
        job = db.scalar(select(Job).where(Job.status == "queued").order_by(Job.created_at).limit(1))
        if not job:
            return None
        result = db.execute(
            update(Job)
            .where(Job.id == job.id, Job.status == "queued")
            .values(status="running", heartbeat=now(), updated_at=now())
        )
        db.commit()
        return job.id if result.rowcount else None


def recover():
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    with Session() as db:
        for job in db.scalars(select(Job).where(Job.status.in_(["running", "cancel_requested"]))).all():
            if not job.heartbeat or job.heartbeat < cutoff:
                job.status = "cancelled" if job.status == "cancel_requested" else "failed"
                job.error_code = "WORKER_INTERRUPTED"
                job.error = "Worker 已中断。可从检查点重试；未收到结果的外部请求可能已计费。"
                job.updated_at = now()
        db.commit()


def heartbeat(job_id, done):
    while not done.wait(5):
        with Session() as db:
            db.execute(update(Job).where(Job.id == job_id).values(heartbeat=now()))
            db.commit()


def execute(job_id):
    done = threading.Event()
    thread = threading.Thread(target=heartbeat, args=(job_id, done), daemon=True)
    thread.start()
    try:
        result = Workflow(job_id).run()
        with Session() as db:
            job = db.get(Job, job_id)
            job.result = result
            job.status = "cancelled" if job.status == "cancel_requested" else "succeeded"
            job.progress, job.stage, job.updated_at = 100, "完成", now()
            db.commit()
    except Cancelled:
        finish_error(job_id, "CANCELLED", "任务已取消", "cancelled")
    except ConfigurationError as exc:
        finish_error(job_id, "CONFIGURATION", str(exc))
    except UncertainRequest as exc:
        finish_error(job_id, "UNCERTAIN_REQUEST", str(exc))
    except (AuthenticationError, PermissionDeniedError):
        finish_error(job_id, "API_ACCESS", "模型服务鉴权或访问失败，请检查后端地址、密钥和模型权限")
    except RateLimitError:
        finish_error(job_id, "API_RATE_LIMIT", "模型服务配额或频率受限，请检查余额或稍后重试")
    except APIStatusError:
        finish_error(job_id, "API_ERROR", "模型服务请求失败，请检查接口协议、模型参数和服务状态")
    except ValueError as exc:
        finish_error(job_id, "VALIDATION", str(exc)[:600])
    except Exception as exc:
        # Log exception class only: provider errors can contain request secrets or user material.
        logger.error("job %s failed: %s", job_id, type(exc).__name__)
        finish_error(job_id, "PROCESSING_ERROR", "处理失败，请检查媒体、模型配置和输入版本后重试")
    finally:
        done.set()
        thread.join(timeout=6)


def finish_error(job_id, code, message, status="failed"):
    with Session() as db:
        job = db.get(Job, job_id)
        job.status, job.error_code, job.error, job.updated_at = status, code, message, now()
        db.commit()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    init_db()
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    recover()
    logger.info("Worker ready")
    while not stopping.is_set():
        job_id = claim()
        if job_id:
            execute(job_id)
        else:
            stopping.wait(1)
            recover()


if __name__ == "__main__":
    main()
