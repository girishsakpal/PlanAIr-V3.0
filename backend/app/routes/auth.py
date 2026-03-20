from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models.user import User
from app.forms import SignupForm, LoginForm

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/')
def landing():
    if current_user.is_authenticated:
        return redirect(url_for('tasks.dashboard'))
    return render_template('landing.html')


@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('tasks.dashboard'))

    form = SignupForm()
    if form.validate_on_submit():
        user = User(
            username=form.username.data,
            email=form.email.data.lower()
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
def login():
    if current_user.is_authenticated:
        return redirect(url_for('tasks.dashboard'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()

        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            flash('Welcome back!', 'success')

            # redirect to the page they were trying to visit, or dashboard
            next_page = request.args.get('next')

            if not user.busy_hours_set:
                return redirect(url_for('schedule.busy_hours_setup'))

            return redirect(next_page or url_for('tasks.dashboard'))

        flash('Incorrect email or password.', 'danger')

    return render_template('auth/login.html', form=form)


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.landing'))


@auth_bp.route('/toggle-dark-mode', methods=['POST'])
@login_required
def toggle_dark_mode():
    current_user.toggle_dark_mode()
    return '', 204  # no content — JS handles the UI update