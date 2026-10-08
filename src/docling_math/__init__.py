"""docling-math package."""

from .corpus_upgrade import upgrade_corpus
from .metadata import PaperMetadata, infer_paper_metadata
from .rename_literature import rename_literature

__version__ = "0.8.0"
__all__ = [
    "PaperMetadata",
    "infer_paper_metadata",
    "rename_literature",
    "upgrade_corpus",
    "__version__",
]
