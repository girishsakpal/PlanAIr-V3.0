from flask import Blueprint, render_template
from flask_login import login_required, current_user
from app.insights import (
    get_weekly_productivity,
    get_weekly_completion,
    get_most_productive_hours,
    get_quadrant_distribution,
    get_mood_trend,
    get_summary_stats,
    get_plain_language_summary
)
import json

insights_bp = Blueprint('insights', __name__)


@insights_bp.route('/insights')
@login_required
def insights():
    stats            = get_summary_stats(current_user.id)
    weekly_prod      = get_weekly_productivity(current_user.id)
    weekly_comp      = get_weekly_completion(current_user.id)
    productive_hours = get_most_productive_hours(current_user.id)
    quadrant_dist    = get_quadrant_distribution(current_user.id)
    mood_trend       = get_mood_trend(current_user.id)

    # find most productive hour
    best_hour = max(productive_hours, key=lambda x: x['count'])
    best_hour_label = (
        best_hour['hour'] if best_hour['count'] > 0 else None
    )

    summary = get_plain_language_summary(stats, best_hour_label)

    return render_template('insights/insights.html',
                           stats=stats,
                           summary=summary,
                           weekly_prod=json.dumps(weekly_prod),
                           weekly_comp=json.dumps(weekly_comp),
                           productive_hours=json.dumps(productive_hours),
                           quadrant_dist=json.dumps(quadrant_dist),
                           mood_trend=json.dumps(mood_trend))