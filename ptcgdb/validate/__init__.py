"""FR-2.3 校验：六条规则 + Markdown 报告（draft→active 的阻断门槛）。"""

from ptcgdb.validate.report import render_report, write_report
from ptcgdb.validate.rules import RuleResult, run_validations

__all__ = ["RuleResult", "render_report", "run_validations", "write_report"]
