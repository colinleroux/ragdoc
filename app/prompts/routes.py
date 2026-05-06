from flask import Blueprint, render_template

from ..models import Prompt, PromptRun

prompts_bp = Blueprint("prompts", __name__, url_prefix="/prompts")


@prompts_bp.route("/")
def index():
    prompts = Prompt.query.order_by(Prompt.updated_at.desc()).all()
    recent_runs = PromptRun.query.order_by(PromptRun.created_at.desc()).limit(8).all()
    return render_template(
        "prompts/index.html",
        prompts=prompts,
        recent_runs=recent_runs,
    )
