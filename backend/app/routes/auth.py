from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models.user import User
from app.models.task import Task
from app.forms import SignupForm, LoginForm
from app.suggestions import clear_all_suggestions
from app.models.schedule import ScheduleSession
from datetime import date, timedelta
from app import limiter

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/')
def landing():
    if current_user.is_authenticated:
        return redirect(url_for('tasks.dashboard'))

    total_users    = User.query.count()
    total_tasks    = Task.query.count()
    total_sessions = ScheduleSession.query.filter_by(is_completed=True).count()

    active_week = User.query.filter(
        User.created_at >= date.today() - timedelta(days=7)
    ).count()

    return render_template('landing.html',
                           total_users=total_users,
                           total_tasks=total_tasks,
                           total_sessions=total_sessions,
                           active_week=active_week)


@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('tasks.dashboard'))

    form = SignupForm()
    if form.validate_on_submit():
        if not form.terms.data:
            flash('You must accept the Terms & Conditions.', 'danger')
            return render_template('auth/signup.html', form=form)
        
        user = User(
            name=form.name.data.strip(),
            username=form.username.data
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash('Account created successfully!', 'success')

        # first-time user → go to busy hours setup
        return redirect(url_for('schedule.busy_hours_setup'))

    return render_template('auth/signup.html', form=form)


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('tasks.dashboard'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()

        if user and user.check_password(form.password.data):
            from datetime import datetime
            user.last_login = datetime.utcnow()
            db.session.commit()
            login_user(user, remember=form.remember.data)
            flash('Welcome back!', 'success')

            # redirect to the page they were trying to visit, or dashboard
            next_page = request.args.get('next')

            if not user.busy_hours_set:
                return redirect(url_for('schedule.busy_hours_setup'))

            return redirect(next_page or url_for('tasks.home'))

        flash('Incorrect username or password.', 'danger')

    return render_template('auth/login.html', form=form)


@auth_bp.route('/logout')
@login_required
def logout():
    clear_all_suggestions(current_user.id)
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.landing'))


@auth_bp.route('/toggle-dark-mode', methods=['POST'])
@login_required
def toggle_dark_mode():
    current_user.toggle_dark_mode()
    return '', 204  # no content JS handles the UI update