from typing import TypedDict


KiCadBomRow = TypedDict(
    'KiCadBomRow',
    {
        'Id': str,
        'Designator': str,
        'Footprint': str,
        # Quantity may be parsed as `int` when coercible, otherwise left as `str`.
        'Quantity': int | str,
        'Designation': str,
        'Supplier and ref': str,
    },
    total=False,
)

__all__ = ['KiCadBomRow']
