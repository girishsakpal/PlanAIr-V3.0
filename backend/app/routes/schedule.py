from flask import Blueprint, render_template
from flask_login import login_required

schedule_bp = Blueprint('schedule', __name__)


@schedule_bp.route('/setup/busy-hours')
@login_required
def busy_hours_setup():
    return render_template('schedule/busy_hours.html')