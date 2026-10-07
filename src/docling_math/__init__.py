"""docling-math package."""

from .metadata import PaperMetadata, infer_paper_metadata
from .rename_literature import rename_literature

__version__ = "0.5.0"
__all__ = [
    "PaperMetadata",
    "infer_paper_metadata",
    "rename_literature",
    "__version__",
]
