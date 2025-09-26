import enum
import os


def get_int_environment_var(name: str, default: int | None, allow_negative=False) -> int:
    """Parse an integer from an environment variable with error handling

    Args:
        name (str): The name of the environment variable to attempt to parse
        default (int | None): The default value to use if the variable is not set.
            if `default` is None, then a ValueError is raised if there is no value
        allow_negative (bool, optional): Wether to allow the parsed value to be negative or not. Defaults to False.

    Raises:
        ValueError: If the value in the variable could not be parsed into an int
        ValueError: If there is no value in the variable and `default` is `None`
        ValueError: If `allow_negative` == `False` and the value is a negative one.

    Returns:
        int: The value in `name` parsed to an int, or the default value
    """

    val = os.environ.get(name)
    if val is not None:
        try:
            parsed = int(val)
        except ValueError:
            raise ValueError(f'Value for variable {name} is not a valid integer: {val}')

        if not allow_negative:
            if parsed < 0:
                raise ValueError(f'Value for variable {name} is not a valid value. It must not be a negative number: {val}')
        return parsed

    else:
        if default is not None:
            return default
        else:
            raise ValueError(f'{name} is a required environment variable')


def get_bool_environment_var(name: str, default: bool | None) -> bool:
    """Attempt to parse a boolean value from an environment variable

    Args:
        name (str): The name of the environment variable to attempt to parse
        default (bool | None): The default value to use if the variable is not set.
            if `default` is None, then a ValueError is raised if there is no value

    Raises:
        ValueError: If the value in the variable could not be parsed into a bool
        ValueError: If there is no value in the variable and `default` is `None`

    Returns:
        bool: The value in `name` parsed to a bool, or the default value
    """
    val = os.environ.get(name)
    if val is not None:
        if val.casefold() == 'true':
            return True
        elif val.casefold() == 'false':
            return False
        else:
            raise ValueError(f'Value for variable {name} is not a valid value. It must be either "True" or "False"')
    else:
        if default is not None:
            return default
        else:
            raise ValueError(f'{name} is a required environment variable')


def get_list_environment_var(name: str, default: list[str] | None) -> list[str]:
    """Attempt to parse a list of strings from an environment variable. The variable must be a comma-delimited string.

    Args:
        name (str): The name of the environment variable to attempt to parse
        default (bool | None): The default value to use if the variable is not set.
            if `default` is None, then a ValueError is raised if there is no value

    Raises:
        ValueError: If the value in the variable could not be parsed into a list of strings
        ValueError: If there is no value in the variable and `default` is `None`

    Returns:
        list[str]: The value in `name` parsed to a `list` of `str`
    """
    val = os.environ.get(name)
    if val is not None:
        # TODO better error handling?
        return [el.strip() for el in val.split(',') if el.strip()]
    else:
        if default is not None:
            return default
        else:
            raise ValueError(f'{name} is a required environment variable')

def get_str_enum_environment_var[T: enum.StrEnum](name: str, default: T | None, enum: type[T]) -> T:
    """_summary_

    Args:
        name (str): The name of the environment variable to attempt to parse
        default (StrEnum | None): The default enum value to use if the variable is not set.
            if `default` is None, then a ValueError is raised if there is no value
        enum (type[StrEnum]): The StrEnum Class to check against to see if the value in `name` is valid

    Raises:
        ValueError: If the value in the variable could not be parsed into a an appropriate value in `enum`
        ValueError: If there is no value in the variable and `default` is `None`

    Returns:
        T: An instance of `enum`
    """
    val = os.environ.get(name)
    if val is not None:
        val = val.casefold()
        # Create a reversed mapping of value->name so that we can find a case-insensitive match to an enum instance
        enum_dict = {e.value.casefold(): e.name for e in enum}
        if (enum_name := enum_dict.get(val, None)) is not None:
            return enum[enum_name]
        else:
            raise ValueError(f'Value for variable {name} is not a valid value. It must be of the following: {', '.join([e.value for e in enum])}')

    else:
        if default is not None:
            return default
        else:
            raise ValueError(f'{name} is a required environment variable')


def get_time_environment_var(name: str, default: tuple[int, int] | None) -> tuple[int, int]:
    def _check_time_bounds(val: tuple[int, int]) -> bool:
        if val[0] > 23 or val[0] < 0:
            return False
        if val[1] > 59 or val[1] < 0:
            return False
        return True

    # double check the default is OK
    if default is not None:
        assert _check_time_bounds(default), f'Default time value for {name} is invalid: {default}'

    val = os.environ.get(name)
    if val is not None:
        # Parse the string and check the bounds
        parts = val.split(':')
        if len(parts) != 2:
            raise ValueError(f'{name} is incorrectly configured. Please use the format "HH:mm"')
        time = (int(parts[0]), int(parts[1]))
        if _check_time_bounds(time):
            return time
        else:
            raise ValueError(f'{name} must have hour values of (0-23) and minutes (0-59)')
    else:
        if default is not None:
            return default
        else:
            raise ValueError(f'{name} is a required environment variable')