from flask import Blueprint, render_template
from flask_login import login_required

insights_bp = Blueprint('insights', __name__)


@insights_bp.route('/insights')
@login_required
def insights():
    return render_template('insights/insights.html')