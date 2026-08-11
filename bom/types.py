from typing import TypedDict


KiCadBomRow = TypedDict(
    'KiCadBomRow',
    {
        'Reference': str,
        'Footprint': str,
        # Qty may be parsed as `int` when coercible, otherwise left as `str`.
        'Qty': int | str,
        'Value': str,
        'LCSC': str,
        'Supplier and ref': str,
    },
    total=False,
)

__all__ = ['KiCadBomRow']
