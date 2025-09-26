from enum import StrEnum
import os
from django.test import TestCase

from bomnado.settings import get_bool_environment_var, get_int_environment_var, get_list_environment_var, get_str_enum_environment_var, get_time_environment_var

class TestIntegerEnvironmentVariableParser(TestCase):
    TEST_VAR_NAME = 'TEST'
    def tearDown(self) -> None:
        if os.environ.get(self.TEST_VAR_NAME, None):
            os.environ.pop(self.TEST_VAR_NAME)

    def test_parses_integers_from_environment(self):
        os.environ.setdefault(self.TEST_VAR_NAME, '12345')
        val = get_int_environment_var(self.TEST_VAR_NAME, None)
        self.assertEqual(val, 12345)

    def test_handles_negative_values(self):
        # Check that by default it does not allow negative values:
        os.environ.setdefault(self.TEST_VAR_NAME, '-12345')
        with self.assertRaises(ValueError):
            get_int_environment_var(self.TEST_VAR_NAME, None)

    def test_parses_negative_values_when_allowed(self):
        os.environ.setdefault(self.TEST_VAR_NAME, '-12345')
        # Check that it handles negative values properly when we allow it
        val = get_int_environment_var(self.TEST_VAR_NAME, None, allow_negative=True)
        self.assertEqual(val, -12345)

    def test_handles_non_integer_values(self):
        os.environ.setdefault(self.TEST_VAR_NAME, 'foo')
        with self.assertRaises(ValueError):
            get_int_environment_var(self.TEST_VAR_NAME, None)

    def test_handles_missing_variable(self):
        # Check that it raises an error if the value is not present and no default was provided
        self.assertNotIn(self.TEST_VAR_NAME, os.environ)
        with self.assertRaises(ValueError):
            get_int_environment_var(self.TEST_VAR_NAME, None)

        val = get_int_environment_var(self.TEST_VAR_NAME, 123456)
        self.assertEqual(val, 123456)

class TestBooleanEnvironmentVariableParser(TestCase):
    TEST_VAR_NAME = 'TEST'
    def tearDown(self) -> None:
        if os.environ.get(self.TEST_VAR_NAME, None):
            os.environ.pop(self.TEST_VAR_NAME)

    def test_parses_bool_from_environment(self):
        # lowercase false
        os.environ.setdefault(self.TEST_VAR_NAME, 'false')
        val = get_bool_environment_var(self.TEST_VAR_NAME, None)
        self.assertFalse(val)
        os.environ.pop(self.TEST_VAR_NAME)

        # uppercase False
        os.environ.setdefault(self.TEST_VAR_NAME, 'False')
        val = get_bool_environment_var(self.TEST_VAR_NAME, None)
        self.assertFalse(val)
        os.environ.pop(self.TEST_VAR_NAME)

        # lowercase true
        os.environ.setdefault(self.TEST_VAR_NAME, 'true')
        val = get_bool_environment_var(self.TEST_VAR_NAME, None)
        self.assertTrue(val)
        os.environ.pop(self.TEST_VAR_NAME)

        # uppercase True
        os.environ.setdefault(self.TEST_VAR_NAME, 'True')
        val = get_bool_environment_var(self.TEST_VAR_NAME, None)
        self.assertTrue(val)
        os.environ.pop(self.TEST_VAR_NAME)

    def test_handles_non_boolean_values(self):
        os.environ.setdefault(self.TEST_VAR_NAME, 'foo')
        with self.assertRaises(ValueError):
            get_bool_environment_var(self.TEST_VAR_NAME, None)

    def test_handles_missing_variable(self):
        # Check that it raises an error if the value is not present and no default was provided
        self.assertNotIn(self.TEST_VAR_NAME, os.environ)
        with self.assertRaises(ValueError):
            get_bool_environment_var(self.TEST_VAR_NAME, None)

        val = get_bool_environment_var(self.TEST_VAR_NAME, False)
        self.assertFalse(val)

        val = get_bool_environment_var(self.TEST_VAR_NAME, True)
        self.assertTrue(val)


class TestStringListEnvironmentVariableParser(TestCase):
    TEST_VAR_NAME = 'TEST'
    def tearDown(self) -> None:
        if os.environ.get(self.TEST_VAR_NAME, None):
            os.environ.pop(self.TEST_VAR_NAME)

    def test_parses_string_list_from_environment(self):
        os.environ.setdefault(self.TEST_VAR_NAME, 'foo,bar,baz')
        val = get_list_environment_var(self.TEST_VAR_NAME, None)
        self.assertListEqual(val, ['foo', 'bar', 'baz'])

    def test_parses_single_values_from_environment(self):
        os.environ.setdefault(self.TEST_VAR_NAME, 'baz')
        val = get_list_environment_var(self.TEST_VAR_NAME, None)
        self.assertListEqual(val, ['baz'])
        os.environ.pop(self.TEST_VAR_NAME)

        os.environ.setdefault(self.TEST_VAR_NAME, '12345')
        val = get_list_environment_var(self.TEST_VAR_NAME, None)
        self.assertListEqual(val, ['12345'])

    def test_handles_missing_variable(self):
        # Check that it raises an error if the value is not present and no default was provided
        self.assertNotIn(self.TEST_VAR_NAME, os.environ)
        with self.assertRaises(ValueError):
            get_list_environment_var(self.TEST_VAR_NAME, None)

        # Test it with a default
        val = get_list_environment_var(self.TEST_VAR_NAME, ['foo', 'bar'])
        self.assertListEqual(val, ['foo', 'bar'])


class TestEnumEnvironmentVariableParser(TestCase):
    class TestEnum(StrEnum):
        TEST_FOO = 'foo'
        TEST_BAR = 'bar'
        TEST_BAZ = 'baz'

    TEST_VAR_NAME = 'TEST'
    def tearDown(self) -> None:
        if os.environ.get(self.TEST_VAR_NAME, None):
            os.environ.pop(self.TEST_VAR_NAME)

    def test_parses_enum_from_environment(self):
        os.environ.setdefault(self.TEST_VAR_NAME, 'foo')
        val = get_str_enum_environment_var(self.TEST_VAR_NAME, None, self.TestEnum)
        self.assertEqual(val, self.TestEnum.TEST_FOO)

        os.environ.pop(self.TEST_VAR_NAME)

        # It should work regardless of case
        os.environ.setdefault(self.TEST_VAR_NAME, 'BAR')
        val = get_str_enum_environment_var(self.TEST_VAR_NAME, None, self.TestEnum)
        self.assertEqual(val, self.TestEnum.TEST_BAR)

        os.environ.pop(self.TEST_VAR_NAME)

        os.environ.setdefault(self.TEST_VAR_NAME, 'bAz')
        val = get_str_enum_environment_var(self.TEST_VAR_NAME, None, self.TestEnum)
        self.assertEqual(val, self.TestEnum.TEST_BAZ)

    def test_handles_wrong_str_from_environment(self):
        os.environ.setdefault(self.TEST_VAR_NAME, 'test')
        with self.assertRaises(ValueError):
            get_str_enum_environment_var(self.TEST_VAR_NAME, None, self.TestEnum)

    def test_handles_missing_variable(self):
        # Check that it raises an error if the value is not present and no default was provided
        self.assertNotIn(self.TEST_VAR_NAME, os.environ)
        with self.assertRaises(ValueError):
            get_str_enum_environment_var(self.TEST_VAR_NAME, None, self.TestEnum)

        # Test it with a default
        val = get_str_enum_environment_var(self.TEST_VAR_NAME, self.TestEnum.TEST_BAR, self.TestEnum)
        self.assertEqual(val, self.TestEnum.TEST_BAR)


class TestTimeEvironmentVariableParser(TestCase):

    TEST_VAR_NAME = 'TEST'
    def tearDown(self) -> None:
        if os.environ.get(self.TEST_VAR_NAME, None):
            os.environ.pop(self.TEST_VAR_NAME)

    def test_parses_times_from_environment(self):
        os.environ.setdefault(self.TEST_VAR_NAME, '22:32')
        val = get_time_environment_var(self.TEST_VAR_NAME, None)
        self.assertTupleEqual(val, (22, 32))

        os.environ.pop(self.TEST_VAR_NAME)

        # It should be permissive with the number format
        os.environ.setdefault(self.TEST_VAR_NAME, '2:1')
        val = get_time_environment_var(self.TEST_VAR_NAME, None)
        self.assertTupleEqual(val, (2, 1))

        os.environ.pop(self.TEST_VAR_NAME)

        os.environ.setdefault(self.TEST_VAR_NAME, '0005:0023')
        val = get_time_environment_var(self.TEST_VAR_NAME, None)
        self.assertTupleEqual(val, (5, 23))

    def test_handles_incorrect_format(self):
        os.environ.setdefault(self.TEST_VAR_NAME, '02:23:32')
        with self.assertRaises(ValueError):
            get_time_environment_var(self.TEST_VAR_NAME, None)

        os.environ.pop(self.TEST_VAR_NAME)

        os.environ.setdefault(self.TEST_VAR_NAME, '12.23')
        with self.assertRaises(ValueError):
            get_time_environment_var(self.TEST_VAR_NAME, None)

        os.environ.pop(self.TEST_VAR_NAME)

        # junk strings should throw an error
        os.environ.setdefault(self.TEST_VAR_NAME, 'foo')
        with self.assertRaises(ValueError):
            get_time_environment_var(self.TEST_VAR_NAME, None)

    def test_handles_numbers_out_of_bounds(self):
        os.environ.setdefault(self.TEST_VAR_NAME, '25:22')
        with self.assertRaises(ValueError):
            get_time_environment_var(self.TEST_VAR_NAME, None)

        os.environ.pop(self.TEST_VAR_NAME)

        os.environ.setdefault(self.TEST_VAR_NAME, '12:60')
        with self.assertRaises(ValueError):
            get_time_environment_var(self.TEST_VAR_NAME, None)

        os.environ.pop(self.TEST_VAR_NAME)

        os.environ.setdefault(self.TEST_VAR_NAME, '-02:00')
        with self.assertRaises(ValueError):
            get_time_environment_var(self.TEST_VAR_NAME, None)

        os.environ.pop(self.TEST_VAR_NAME)

        os.environ.setdefault(self.TEST_VAR_NAME, '02:-20')
        with self.assertRaises(ValueError):
            get_time_environment_var(self.TEST_VAR_NAME, None)

    def test_handles_missing_variable(self):
        # Check that it raises an error if the value is not present and no default was provided
        self.assertNotIn(self.TEST_VAR_NAME, os.environ)
        with self.assertRaises(ValueError):
            get_time_environment_var(self.TEST_VAR_NAME, None)

        # Test it with a default
        val = get_time_environment_var(self.TEST_VAR_NAME, (21, 52))
        self.assertTupleEqual(val, (21, 52))