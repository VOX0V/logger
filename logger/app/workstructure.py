"""Structure of the work data: the fields chosen among the entities (see fields.py), the same for all accounts."""
from . import fields


def columns():
    """[{column, display_name, position, data_type, visible, editable, nullable}] of the work data, in order."""
    return fields.columns("work")
