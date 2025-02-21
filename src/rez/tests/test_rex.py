# Copyright Contributors to the Rez project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""
test the rex command generator API
"""
from rez.rex import RexExecutor, Python, Setenv, Appendenv, Prependenv, Info, \
    Comment, Alias, Command, Source, Error, Shebang, Unsetenv, expandable, \
    literal
from rez.rex_bindings import VersionBinding, VariantBinding, VariantsBinding, \
    RequirementsBinding, EphemeralsBinding, intersects
from rez.exceptions import RexError, RexUndefinedVariableError
from rez.config import config
import unittest
from rez.vendor.version.version import Version
from rez.vendor.version.requirement import Requirement
from rez.tests.util import TestBase
from rez.utils.backcompat import convert_old_commands
from rez.package_repository import package_repository_manager
from rez.packages import iter_package_families
import inspect
import textwrap
import os


class TestRex(TestBase):

    def _create_executor(self, env, **kwargs):
        interp = Python(target_environ={}, passive=True)
        return RexExecutor(interpreter=interp,
                           parent_environ=env,
                           shebang=False,
                           **kwargs)

    def _test(self, func, env, expected_actions=None, expected_output=None,
              expected_exception=None, **ex_kwargs):
        """Tests rex code as a function object, and code string."""
        loc = inspect.getsourcelines(func)[0][1:]
        code = textwrap.dedent('\n'.join(loc))

        if expected_exception:
            ex = self._create_executor(env, **ex_kwargs)
            self.assertRaises(expected_exception, ex.execute_function, func)

            ex = self._create_executor(env, **ex_kwargs)
            self.assertRaises(expected_exception, ex.execute_code, code)
        else:
            ex = self._create_executor(env, **ex_kwargs)
            ex.execute_function(func)
            self.assertEqual(ex.actions, expected_actions)
            self.assertEqual(ex.get_output(), expected_output)

            ex = self._create_executor(env, **ex_kwargs)
            ex.execute_code(code)
            self.assertEqual(ex.actions, expected_actions)
            self.assertEqual(ex.get_output(), expected_output)

    def test_1(self):
        """Test simple use of every available action."""
        def _rex():
            shebang()
            setenv("FOO", "foo")
            setenv("BAH", "bah")
            getenv("BAH")
            unsetenv("BAH")
            unsetenv("NOTEXIST")
            prependenv("A", "/tmp")
            prependenv("A", "/data")
            appendenv("B", "/tmp")
            appendenv("B", "/data")
            defined("BAH")
            undefined("BAH")
            defined("NOTEXIST")
            undefined("NOTEXIST")
            alias("thing", "thang")
            info("that's interesting")
            error("oh noes")
            command("runme --with --args")
            source("./script.src")

        self._test(func=_rex,
                   env={},
                   expected_actions=[
                       Shebang(),
                       Setenv('FOO', 'foo'),
                       Setenv('BAH', 'bah'),
                       Unsetenv('BAH'),
                       Unsetenv('NOTEXIST'),
                       Setenv('A', '/tmp'),
                       Prependenv('A', '/data'),
                       Setenv('B', '/tmp'),
                       Appendenv('B', '/data'),
                       Alias('thing', 'thang'),
                       Info("that's interesting"),
                       Error('oh noes'),
                       Command('runme --with --args'),
                       Source('./script.src')],
                   expected_output={
                       'FOO': 'foo',
                       'A': os.pathsep.join(["/data", "/tmp"]),
                       'B': os.pathsep.join(["/tmp", "/data"])})

    def test_2(self):
        """Test simple setenvs and assignments."""
        def _rex():
            env.FOO = "foo"
            setenv("BAH", "bah")
            env.EEK = env.FOO

        self._test(func=_rex,
                   env={},
                   expected_actions=[
                       Setenv('FOO', 'foo'),
                       Setenv('BAH', 'bah'),
                       Setenv('EEK', 'foo')],
                   expected_output={
                       'FOO': 'foo',
                       'EEK': 'foo',
                       'BAH': 'bah'})

    def test_3(self):
        """Test appending/prepending."""
        def _rex():
            appendenv("FOO", "test1")
            env.FOO.append("test2")
            env.FOO.append("test3")

            env.BAH.prepend("A")
            prependenv("BAH", "B")
            env.BAH.append("C")

        # no parent variables enabled
        self._test(func=_rex,
                   env={},
                   expected_actions=[
                       Setenv('FOO', 'test1'),
                       Appendenv('FOO', 'test2'),
                       Appendenv('FOO', 'test3'),
                       Setenv('BAH', 'A'),
                       Prependenv('BAH', 'B'),
                       Appendenv('BAH', 'C')],
                   expected_output={
                       'FOO': os.pathsep.join(["test1", "test2", "test3"]),
                       'BAH': os.pathsep.join(["B", "A", "C"])})

        # FOO and BAH enabled as parent variables, but not present
        expected_actions = [Appendenv('FOO', 'test1'),
                            Appendenv('FOO', 'test2'),
                            Appendenv('FOO', 'test3'),
                            Prependenv('BAH', 'A'),
                            Prependenv('BAH', 'B'),
                            Appendenv('BAH', 'C')]

        self._test(func=_rex,
                   env={},
                   expected_actions=expected_actions,
                   expected_output={
                       'FOO': os.pathsep.join(["", "test1", "test2", "test3"]),
                       'BAH': os.pathsep.join(["B", "A", "", "C"])},
                   parent_variables=["FOO", "BAH"])

        # FOO and BAH enabled as parent variables, and present
        self._test(func=_rex,
                   env={"FOO": "tmp",
                        "BAH": "Z"},
                   expected_actions=expected_actions,
                   expected_output={
                       'FOO': os.pathsep.join(["tmp", "test1", "test2", "test3"]),
                       'BAH': os.pathsep.join(["B", "A", "Z", "C"])},
                   parent_variables=["FOO", "BAH"])

    def test_4(self):
        """Test control flow using internally-set env vars."""
        def _rex():
            env.FOO = "foo"
            setenv("BAH", "bah")
            env.EEK = "foo"

            if env.FOO == "foo":
                env.FOO_VALID = 1
                info("FOO validated")

            if env.FOO == env.EEK:
                comment("comparison ok")

        self._test(func=_rex,
                   env={},
                   expected_actions=[
                       Setenv('FOO', 'foo'),
                       Setenv('BAH', 'bah'),
                       Setenv('EEK', 'foo'),
                       Setenv('FOO_VALID', '1'),
                       Info('FOO validated'),
                       Comment('comparison ok')],
                   expected_output={
                       'FOO': 'foo',
                       'BAH': 'bah',
                       'EEK': 'foo',
                       'FOO_VALID': '1'})

    def test_5(self):
        """Test control flow using externally-set env vars."""
        def _rex():
            if defined("EXT") and env.EXT == "alpha":
                env.EXT_FOUND = 1
                env.EXT.append("beta")  # will still overwrite
            else:
                env.EXT_FOUND = 0
                if undefined("EXT"):
                    info("undefined working as expected")

        # with EXT undefined
        self._test(func=_rex,
                   env={},
                   expected_actions=[
                       Setenv('EXT_FOUND', '0'),
                       Info("undefined working as expected")],
                   expected_output={'EXT_FOUND': '0'})

        # with EXT defined
        self._test(func=_rex,
                   env={"EXT": "alpha"},
                   expected_actions=[
                       Setenv('EXT_FOUND', '1'),
                       Setenv('EXT', 'beta')],
                   expected_output={
                       'EXT_FOUND': '1',
                       'EXT': 'beta'})

    def test_6(self):
        """Test variable expansion."""
        def _rex():
            env.FOO = "foo"
            env.DOG = "$FOO"  # this will convert to '${FOO}'
            env.BAH = "${FOO}"
            env.EEK = "${BAH}"
            if env.BAH == "foo" and getenv("EEK") == "foo":
                info("expansions visible in control flow")

            if defined("EXT") and getenv("EXT") == "alpha":
                env.FEE = "${EXT}"

        # with EXT undefined
        self._test(func=_rex,
                   env={},
                   expected_actions=[
                       Setenv('FOO', 'foo'),
                       Setenv('DOG', '${FOO}'),
                       Setenv('BAH', '${FOO}'),
                       Setenv('EEK', '${BAH}'),
                       Info('expansions visible in control flow')],
                   expected_output={
                       'FOO': 'foo',
                       'DOG': 'foo',
                       'BAH': 'foo',
                       'EEK': 'foo'})

        # with EXT defined
        self._test(func=_rex,
                   env={"EXT": "alpha"},
                   expected_actions=[
                       Setenv('FOO', 'foo'),
                       Setenv('DOG', '${FOO}'),
                       Setenv('BAH', '${FOO}'),
                       Setenv('EEK', '${BAH}'),
                       Info('expansions visible in control flow'),
                       Setenv('FEE', '${EXT}')],
                   expected_output={
                       'FOO': 'foo',
                       'DOG': 'foo',
                       'BAH': 'foo',
                       'EEK': 'foo',
                       'FEE': 'alpha'})

    def test_7(self):
        """Test exceptions."""
        def _rex1():
            # reference to undefined var
            getenv("NOTEXIST")

        self._test(func=_rex1,
                   env={},
                   expected_exception=RexUndefinedVariableError)

        def _rex2():
            # reference to undefined var
            info(env.NOTEXIST)

        self._test(func=_rex2,
                   env={},
                   expected_exception=RexUndefinedVariableError)

        def _rex3():
            # native error, this gets encapsulated in a RexError
            raise Exception("some non rex-specific error")

        self._test(func=_rex3,
                   env={},
                   expected_exception=RexError)

    def test_8(self):
        """Custom environment variable separators."""

        config.override("env_var_separators", {"FOO": ",", "BAH": " "})

        def _rex():
            appendenv("FOO", "test1")
            env.FOO.append("test2")
            env.FOO.append("test3")

            env.BAH.prepend("A")
            prependenv("BAH", "B")
            env.BAH.append("C")

        self._test(func=_rex,
                   env={},
                   expected_actions=[
                       Setenv('FOO', 'test1'),
                       Appendenv('FOO', 'test2'),
                       Appendenv('FOO', 'test3'),
                       Setenv('BAH', 'A'),
                       Prependenv('BAH', 'B'),
                       Appendenv('BAH', 'C')],
                   expected_output={
                       'FOO': ",".join(["test1", "test2", "test3"]),
                       'BAH': " ".join(["B", "A", "C"])})

    def test_9(self):
        """Test literal and expandable strings."""
        def _rex():
            env.A = "hello"
            env.FOO = expandable("$A")  # will convert to '${A}'
            env.BAH = expandable("${A}")
            env.EEK = literal("$A")

        def _rex2():
            env.BAH = "omg"
            env.FOO.append("$BAH")
            env.FOO.append(literal("${BAH}"))
            env.FOO.append(expandable("like, ").l("$SHE said, ").e("$BAH"))

        self._test(func=_rex,
                   env={},
                   expected_actions=[
                       Setenv('A', 'hello'),
                       Setenv('FOO', '${A}'),
                       Setenv('BAH', '${A}'),
                       Setenv('EEK', '$A')],
                   expected_output={
                       'A': 'hello',
                       'FOO': 'hello',
                       'BAH': 'hello',
                       'EEK': '$A'})

        self._test(func=_rex2,
                   env={},
                   expected_actions=[
                       Setenv('BAH', 'omg'),
                       Setenv('FOO', '${BAH}'),
                       Appendenv('FOO', '${BAH}'),
                       Appendenv('FOO', 'like, $SHE said, ${BAH}')],
                   expected_output={
                       'BAH': 'omg',
                       'FOO': os.pathsep.join(['omg', '${BAH}', 'like']) + ', $SHE said, omg'})

    def test_10(self):
        """Test env __contains__ and __bool__"""

        def _test(func, env, expected):
            ex = self._create_executor(env=env)
            self.assertEqual(expected, ex.execute_function(func))

        def _rex_1():
            return {
                "A": "A" in env.keys(),
                "B": "B" in env.keys(),
            }

        def _rex_2():
            return {
                "A": "A" in env,
                "B": "B" in env,
            }

        def _rex_3():
            return env.get("B") or "not b"

        _test(_rex_1, env={"A": "foo"}, expected={"A": True, "B": False})
        _test(_rex_2, env={"A": "foo"}, expected={"A": True, "B": False})
        _test(_rex_3, env={}, expected="not b")

    def test_version_binding(self):
        """Test the Rex binding of the Version class."""
        v = VersionBinding(Version("1.2.3alpha"))
        self.assertEqual(v.major, 1)
        self.assertEqual(v.minor, 2)
        self.assertEqual(v.patch, "3alpha")
        self.assertEqual(len(v), 3)
        self.assertEqual(v[1], 2)
        self.assertEqual(v[:2], (1, 2))
        self.assertEqual(str(v), "1.2.3alpha")
        self.assertEqual(v[5], None)
        self.assertEqual(v.as_tuple(), (1, 2, "3alpha"))

    def test_old_style_commands(self):
        """Convert old style commands to rex"""
        expected = ""
        rez_commands = convert_old_commands([], annotate=False)
        self.assertEqual(rez_commands, expected)

        expected = "setenv('A', 'B')"
        rez_commands = convert_old_commands(["export A=B"], annotate=False)
        self.assertEqual(rez_commands, expected)

        expected = "setenv('A', 'B:$C')"
        rez_commands = convert_old_commands(["export A=B:$C"], annotate=False)
        self.assertEqual(rez_commands, expected)

        expected = "setenv('A', 'hey \"there\"')"
        rez_commands = convert_old_commands(['export A="hey \\"there\\""'],
                                            annotate=False)
        self.assertEqual(rez_commands, expected)

        expected = "appendenv('A', 'B')"
        rez_commands = convert_old_commands(["export A=$A:B"], annotate=False)
        self.assertEqual(rez_commands, expected)

        expected = "prependenv('A', 'B')"
        rez_commands = convert_old_commands(["export A=B:$A"], annotate=False)
        self.assertEqual(rez_commands, expected)

        expected = "appendenv('A', 'B:$C')"
        rez_commands = convert_old_commands(["export A=$A:B:$C"],
                                            annotate=False)
        self.assertEqual(rez_commands, expected)

        expected = "prependenv('A', '$C:B')"
        rez_commands = convert_old_commands(["export A=$C:B:$A"],
                                            annotate=False)
        self.assertEqual(rez_commands, expected)

    def test_intersects_resolve(self):
        """Test intersects with resolve object"""
        resolved_pkg_data = {
            "foo": {"1": {"name": "foo", "version": "1"}},
            "maya": {"2020.1": {"name": "maya", "version": "2020.1"}},
        }
        mem_path = "memory@%s" % hex(id(resolved_pkg_data))
        resolved_repo = package_repository_manager.get_repository(mem_path)
        resolved_repo.data = resolved_pkg_data
        resolved_packages = [
            variant
            for family in iter_package_families(paths=[mem_path])
            for package in family.iter_packages()
            for variant in package.iter_variants()
        ]

        variant_bindings = dict(
            (variant.name, VariantBinding(variant))
            for variant in resolved_packages
        )
        resolve = VariantsBinding(variant_bindings)

        self.assertTrue(intersects(resolve.foo, "1"))
        self.assertFalse(intersects(resolve.foo, "0"))
        self.assertTrue(intersects(resolve.maya, "2019+"))
        self.assertFalse(intersects(resolve.maya, "<=2019"))

    def test_intersects_request(self):
        """Test intersects with request object"""
        # request.get
        request = RequirementsBinding([Requirement("foo.bar-1")])
        bar_on = intersects(request.get("foo.bar", "0"), "1")
        self.assertTrue(bar_on)

        request = RequirementsBinding([])
        bar_on = intersects(request.get("foo.bar", "0"), "1")
        self.assertTrue(bar_on)  # should be False, but for backward compat

        request = RequirementsBinding([])
        bar_on = intersects(request.get("foo.bar", "foo.bar-0"), "1")
        self.assertFalse(bar_on)  # workaround, see PR nerdvegas/rez#1030

        # request.get_range
        request = RequirementsBinding([Requirement("foo.bar-1")])
        bar_on = intersects(request.get_range("foo.bar", "0"), "1")
        self.assertTrue(bar_on)

        request = RequirementsBinding([])
        bar_on = intersects(request.get_range("foo.bar", "0"), "1")
        self.assertFalse(bar_on)

        request = RequirementsBinding([])
        foo = intersects(request.get_range("foo", "==1.2.3"), "1.2")
        self.assertTrue(foo)

        request = RequirementsBinding([])
        foo = intersects(request.get_range("foo", "==1.2.3"), "1.4")
        self.assertFalse(foo)

        request = RequirementsBinding([Requirement("foo-1.4.5")])
        foo = intersects(request.get_range("foo", "==1.2.3"), "1.4")
        self.assertTrue(foo)

    def test_intersects_ephemerals(self):
        """Test intersects with ephemerals object"""
        # ephemerals.get
        ephemerals = EphemeralsBinding([Requirement(".foo.bar-1")])
        bar_on = intersects(ephemerals.get("foo.bar", "0"), "1")
        self.assertTrue(bar_on)

        ephemerals = EphemeralsBinding([])
        bar_on = intersects(ephemerals.get("foo.bar", "0"), "1")
        self.assertTrue(bar_on)  # should be False, but for backward compat

        ephemerals = EphemeralsBinding([])
        bar_on = intersects(ephemerals.get("foo.bar", "foo.bar-0"), "1")
        self.assertFalse(bar_on)  # workaround, see PR nerdvegas/rez#1030

        ephemerals = EphemeralsBinding([])
        self.assertRaises(RuntimeError,  # no default
                          intersects, ephemerals.get("foo.bar"), "0")

        # ephemerals.get_range
        ephemerals = EphemeralsBinding([Requirement(".foo.bar-1")])
        bar_on = intersects(ephemerals.get_range("foo.bar", "0"), "1")
        self.assertTrue(bar_on)

        ephemerals = EphemeralsBinding([])
        bar_on = intersects(ephemerals.get_range("foo.bar", "0"), "1")
        self.assertFalse(bar_on)

        ephemerals = EphemeralsBinding([])
        foo = intersects(ephemerals.get_range("foo", "==1.2.3"), "1.2")
        self.assertTrue(foo)

        ephemerals = EphemeralsBinding([])
        foo = intersects(ephemerals.get_range("foo", "==1.2.3"), "1.4")
        self.assertFalse(foo)

        ephemerals = EphemeralsBinding([Requirement(".foo-1.4.5")])
        foo = intersects(ephemerals.get_range("foo", "==1.2.3"), "1.4")
        self.assertTrue(foo)

        ephemerals = EphemeralsBinding([])
        self.assertRaises(RuntimeError,  # no default
                          intersects, ephemerals.get_range("foo.bar"), "0")


if __name__ == '__main__':
    unittest.main()
