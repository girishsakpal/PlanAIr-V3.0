# from flask import Blueprint

# auth_bp = Blueprint('auth', __name__)

from flask_login import login_user
from flask import redirect, url_for
import user

login_user(user)

if not user.busy_hours_set:
    return redirect(url_for('schedule.busy_hours_setup'))

return redirect(url_for('tasks.dashboard'))