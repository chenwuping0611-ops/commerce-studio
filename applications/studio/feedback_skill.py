from pathlib import Path


FEEDBACK_SKILL_CODE = "studio-feedback-quality"
FEEDBACK_SKILL_NAME = "通用意见反馈与产品约束维护"
FEEDBACK_SKILL_FILE_NAME = "studio-feedback-quality.md"


def feedback_skill_path():
    return Path(__file__).with_name("feedback_quality.md")


def load_feedback_skill_content():
    path = feedback_skill_path()
    return path.read_text(encoding="utf-8")
