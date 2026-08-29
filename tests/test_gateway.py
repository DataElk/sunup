"""The public weather gateway must stay narrow and keep its secret server-side."""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_gateway_contract():
    result = subprocess.run(
        ["node", "--test", "gateway/test/index.test.mjs"],
        cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_gateway_configuration_contains_names_not_secrets():
    source = open(os.path.join(ROOT, "gateway", "wrangler.jsonc"),
                  encoding="utf-8").read()
    assert '"required": ["FORTYGUARD_API_KEY"]' in source
    assert '"SUBMIT_LIMITER"' in source
    assert '"STATUS_LIMITER"' in source
    assert '"FORTYGUARD_API_KEY":' not in source


def test_gateway_is_not_a_general_api_proxy():
    source = open(os.path.join(ROOT, "gateway", "src", "index.mjs"),
                  encoding="utf-8").read()
    assert "url.pathname === '/v1/heatmap'" in source
    assert "url.pathname.match(/^\\/v1\\/status\\/" in source
    assert "new URL(path, UPSTREAM_ORIGIN)" in source
    assert "new URL(url.pathname" not in source
    assert "validateHeatmapPayload(payload)" in source
