from __future__ import annotations

import types
import typing

from pydantic import BaseModel


def _noncatalog_leaves(model: type[BaseModel], prefix: str = "") -> set[str]:
    leaves: set[str] = set()
    for name, field in model.model_fields.items():
        annotation = field.annotation
        if typing.get_origin(annotation) in (typing.Union, types.UnionType):
            annotation = next(
                (item for item in typing.get_args(annotation) if item is not type(None)),
                annotation,
            )
        path = prefix + name
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            leaves |= _noncatalog_leaves(annotation, path + ".")
        elif not isinstance(field.json_schema_extra, dict) or "group" not in field.json_schema_extra:
            leaves.add(path)
    return leaves


def test_every_config_leaf_outside_catalog_has_product_classification():
    from jaeger_ai.core.instance.schemas import Config
    from jaeger_ai.core.settings.exposure import NONCATALOG_EXPOSURE

    assert set(NONCATALOG_EXPOSURE) == _noncatalog_leaves(Config)
    assert set(NONCATALOG_EXPOSURE.values()) <= {
        "dedicated_ui", "advanced_cli", "internal", "secret", "secret_reference",
    }
