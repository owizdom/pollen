"""Track C: parent inference (spec 0001 v2.2 sections 3.3, 8)."""
from lineage.declared import declared_base
from lineage.parents import ParentLink, ParentResult

__all__ = ["ParentLink", "ParentResult", "declared_base"]
