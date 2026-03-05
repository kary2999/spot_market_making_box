"""
单元测试 — SQL/JSON 输出模块 (src/output.py)
覆盖：SQL 转义、字段格式化、SQL 文件生成、JSON 文件生成、控制台摘要输出
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from src.output import (
    _config_to_sql_row,
    _escape_str,
    _value_to_sql,
    generate_json,
    generate_sql,
    print_summary,
)


# ---------------------------------------------------------------------------
# 测试夹具
# ---------------------------------------------------------------------------


def _make_config(
    *,
    direction: int = -1,
    dom: int = 1,
    trust_num: int = 50,
    price_float: str = "95000.00-95000.02",
    number_float: str = "0.001-0.002",
    change_trust_num: int = 0,
    change_number_float: str = "0.001-0.002",
    change_survival_time: str = "3-10",
    pid: int = 1,
    status: int = 1,
    zone: str = "near",
    direction_label: str = "卖",
) -> dict:
    return {
        "box_id": None,
        "pid": pid,
        "direction": direction,
        "dom": dom,
        "trust_num": trust_num,
        "price_float": price_float,
        "number_float": number_float,
        "change_trust_num": change_trust_num,
        "change_number_float": change_number_float,
        "change_survival_time": change_survival_time,
        "status": status,
        "_symbol": "BTCUSDT",
        "_zone": zone,
        "_direction_label": direction_label,
    }


@pytest.fixture
def single_config():
    return _make_config()


@pytest.fixture
def multi_configs():
    return [
        _make_config(dom=1, direction=-1, trust_num=50),
        _make_config(dom=2, direction=-1, trust_num=100,
                     price_float="95000.02-95000.12",
                     zone="mid", change_trust_num=1,
                     change_survival_time="10-30"),
        _make_config(dom=1, direction=1, trust_num=50,
                     price_float="94999.98-95000.00",
                     direction_label="买"),
    ]


# ---------------------------------------------------------------------------
# _escape_str
# ---------------------------------------------------------------------------


class TestEscapeStr:
    def test_clean_price_float(self):
        assert _escape_str("95000.00-95000.02") == "95000.00-95000.02"

    def test_removes_sql_injection_chars(self):
        result = _escape_str("'; DROP TABLE t; --")
        # Should only contain digits, dots, dashes
        assert "'" not in result
        assert ";" not in result
        assert "D" not in result

    def test_allows_digits_dot_dash(self):
        result = _escape_str("1.5-2.3")
        assert result == "1.5-2.3"

    def test_non_string_converted(self):
        result = _escape_str(42)
        assert result == "42"

    def test_empty_string(self):
        assert _escape_str("") == ""

    def test_only_letters_stripped(self):
        result = _escape_str("abc123")
        assert result == "123"

    def test_unicode_stripped(self):
        result = _escape_str("价格100.5")
        assert result == "100.5"


# ---------------------------------------------------------------------------
# _value_to_sql
# ---------------------------------------------------------------------------


class TestValueToSql:
    def test_none_returns_null(self):
        assert _value_to_sql("box_id", None) == "null"

    def test_str_field_quoted(self):
        result = _value_to_sql("price_float", "100.0-101.0")
        assert result == "'100.0-101.0'"

    def test_int_field_unquoted(self):
        assert _value_to_sql("direction", -1) == "-1"

    def test_status_as_int(self):
        assert _value_to_sql("status", 1) == "1"

    def test_trust_num_as_int(self):
        assert _value_to_sql("trust_num", 100) == "100"

    def test_number_float_quoted(self):
        result = _value_to_sql("number_float", "0.001-0.002")
        assert result.startswith("'") and result.endswith("'")

    def test_change_number_float_quoted(self):
        result = _value_to_sql("change_number_float", "0.5-1.0")
        assert result.startswith("'") and result.endswith("'")

    def test_change_survival_time_quoted(self):
        result = _value_to_sql("change_survival_time", "10-30")
        assert result.startswith("'") and result.endswith("'")

    def test_dom_as_int(self):
        assert _value_to_sql("dom", 3) == "3"


# ---------------------------------------------------------------------------
# _config_to_sql_row
# ---------------------------------------------------------------------------


class TestConfigToSqlRow:
    def test_returns_parenthesized_row(self, single_config):
        row = _config_to_sql_row(single_config)
        assert row.strip().startswith("(")
        assert row.strip().endswith(")")

    def test_null_for_box_id(self, single_config):
        row = _config_to_sql_row(single_config)
        assert "null" in row

    def test_contains_correct_pid(self, single_config):
        row = _config_to_sql_row(single_config)
        assert "1" in row  # pid=1

    def test_contains_trust_num(self, single_config):
        row = _config_to_sql_row(single_config)
        assert "50" in row

    def test_internal_fields_excluded(self, single_config):
        row = _config_to_sql_row(single_config)
        # _symbol, _zone, _direction_label should not appear
        assert "BTCUSDT" not in row
        assert "near" not in row
        assert "卖" not in row


# ---------------------------------------------------------------------------
# generate_sql
# ---------------------------------------------------------------------------


class TestGenerateSql:
    def test_creates_file(self, multi_configs):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "output.sql")
            generate_sql(multi_configs, path)
            assert os.path.exists(path)

    def test_file_starts_with_insert(self, multi_configs):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "output.sql")
            generate_sql(multi_configs, path)
            content = open(path, encoding="utf-8").read()
            assert content.startswith("INSERT INTO spot_market_making_box")

    def test_file_ends_with_semicolon(self, multi_configs):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "output.sql")
            generate_sql(multi_configs, path)
            content = open(path, encoding="utf-8").read().strip()
            assert content.endswith(";")

    def test_correct_number_of_value_rows(self, multi_configs):
        """VALUES 行数 == 配置条数"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "output.sql")
            generate_sql(multi_configs, path)
            content = open(path, encoding="utf-8").read()
            # Count value rows: lines that start with '(' but are not the field list
            lines = content.splitlines()
            in_values = False
            rows = []
            for ln in lines:
                if ln.strip().startswith("VALUES"):
                    in_values = True
                    continue
                if in_values and ln.strip().startswith("("):
                    rows.append(ln)
            assert len(rows) == len(multi_configs)

    def test_creates_parent_dirs(self, multi_configs):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "nested", "dir", "output.sql")
            generate_sql(multi_configs, path)
            assert os.path.exists(path)

    def test_contains_field_names(self, multi_configs):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "output.sql")
            generate_sql(multi_configs, path)
            content = open(path, encoding="utf-8").read()
            assert "trust_num" in content
            assert "price_float" in content

    def test_single_config_no_trailing_comma(self, single_config):
        """单条记录不应有多余的逗号分隔符"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "output.sql")
            generate_sql([single_config], path)
            content = open(path, encoding="utf-8").read()
            # There should be exactly one value row
            rows = [ln for ln in content.splitlines() if ln.strip().startswith("(")]
            assert len(rows) == 1


# ---------------------------------------------------------------------------
# generate_json
# ---------------------------------------------------------------------------


class TestGenerateJson:
    def test_creates_file(self, multi_configs):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "output.json")
            generate_json(multi_configs, path)
            assert os.path.exists(path)

    def test_valid_json(self, multi_configs):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "output.json")
            generate_json(multi_configs, path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)  # must not raise
            assert isinstance(data, list)

    def test_output_count_matches_input(self, multi_configs):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "output.json")
            generate_json(multi_configs, path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            assert len(data) == len(multi_configs)

    def test_internal_fields_stripped(self, multi_configs):
        """以 _ 开头的字段不应出现在输出中"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "output.json")
            generate_json(multi_configs, path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                for key in item:
                    assert not key.startswith("_"), f"Internal field '{key}' leaked into JSON"

    def test_public_fields_present(self, multi_configs):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "output.json")
            generate_json(multi_configs, path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            required_keys = {"pid", "direction", "dom", "trust_num", "status"}
            for item in data:
                assert required_keys.issubset(item.keys())

    def test_creates_parent_dirs(self, multi_configs):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "nested", "dir", "output.json")
            generate_json(multi_configs, path)
            assert os.path.exists(path)

    def test_single_config_list_output(self, single_config):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "out.json")
            generate_json([single_config], path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            assert len(data) == 1


# ---------------------------------------------------------------------------
# print_summary
# ---------------------------------------------------------------------------


class TestPrintSummary:
    def test_runs_without_error(self, multi_configs, capsys):
        print_summary(multi_configs)

    def test_prints_header(self, multi_configs, capsys):
        print_summary(multi_configs)
        out = capsys.readouterr().out
        assert "铺单配置摘要" in out

    def test_prints_config_count(self, multi_configs, capsys):
        print_summary(multi_configs)
        out = capsys.readouterr().out
        assert f"共 {len(multi_configs)} 条配置" in out

    def test_direction_label_shown(self, multi_configs, capsys):
        print_summary(multi_configs)
        out = capsys.readouterr().out
        assert "卖" in out
        assert "买" in out

    def test_zone_label_shown(self, multi_configs, capsys):
        print_summary(multi_configs)
        out = capsys.readouterr().out
        assert "近盘" in out
        assert "中盘" in out

    def test_empty_configs_runs(self, capsys):
        """空列表不应抛出异常"""
        print_summary([])
        out = capsys.readouterr().out
        assert "共 0 条配置" in out

    def test_missing_direction_label_fallback(self, capsys):
        """缺少 _direction_label 时使用 direction 数值"""
        config = _make_config()
        del config["_direction_label"]
        print_summary([config])
        out = capsys.readouterr().out
        assert "-1" in out  # direction 数值

    def test_missing_zone_fallback(self, capsys):
        """缺少 _zone 时不崩溃"""
        config = _make_config()
        del config["_zone"]
        print_summary([config])  # must not raise
