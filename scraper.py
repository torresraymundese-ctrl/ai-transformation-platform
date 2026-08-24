"""Retired direct-publication scraper metadata and safety gate.

Task 5B replaces this temporary gate with the reviewed ingestion queue.
"""


INGESTION_QUEUE_NOT_READY = "ingestion_queue_not_ready"

# Future queue adapters retain these source identities, but must not fetch or
# publish until the reviewed ingestion queue is available.
SOURCE_ADAPTERS = (
    {"name": "机器之心", "url": "https://synced.com", "category": "insight"},
    {"name": "量子位", "url": "https://www.qbitai.com", "category": "insight"},
    {"name": "CSDN", "url": "https://blog.csdn.net/nav/ai", "category": "tech"},
    {
        "name": "阿里云开发者",
        "url": "https://developer.aliyun.com/article",
        "category": "tech",
    },
    {
        "name": "华为云开发者",
        "url": "https://developer.huaweicloud.com/develop/aigallery/home.html",
        "category": "tech",
    },
    {"name": "AI Era", "url": "https://aiera.cn", "category": "insight"},
    {
        "name": "36氪",
        "url": "https://36kr.com/search/articles/%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD",
        "category": "insight",
    },
    {"name": "InfoQ", "url": "https://www.infoq.cn/topic/ai", "category": "whitepaper"},
)


class IngestionQueueNotReadyError(RuntimeError):
    """Raised when retired direct publication is invoked before queue rollout."""


def run_scraper():
    """Fail closed so scripts cannot bypass reviewed ingestion and publication."""
    raise IngestionQueueNotReadyError(INGESTION_QUEUE_NOT_READY)


if __name__ == "__main__":
    run_scraper()
