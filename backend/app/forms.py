from flask_wtf import FlaskForm
from wtforms import (StringField, PasswordField, BooleanField, SubmitField,
                     TextAreaField, IntegerField, FloatField, DateField,
                     SelectField, HiddenField, TimeField)
from wtforms.validators import (DataRequired, EqualTo, Length,
                                ValidationError, Optional, NumberRange, Regexp)
from app.models.user import User


from flask import current_app

class SignupForm(FlaskForm):
    name = StringField('Your Name', validators=[
        DataRequired(),
        Length(min=1, max=120, message='Name must be 1–120 characters')
    ])
    username = StringField('Username', validators=[
        DataRequired(),
        Length(min=3, max=80, message='Username must be 3–80 characters'),
        Regexp(r'^[a-zA-Z0-9._]+$',
               message='Username may only contain letters, numbers, dots, and underscores')
    ])
    password = PasswordField('Password', validators=[
        DataRequired(),
        Length(min=8, message='Password must be at least 8 characters')
    ])
    confirm_password = PasswordField('Confirm Password', validators=[
        DataRequired(),
        EqualTo('password', message='Passwords must match')
    ])
    promo_code = StringField('Promo Code', validators=[
        DataRequired(message='A promo code is required to sign up')
    ])
    terms = BooleanField('I agree to the Terms & Conditions')
    submit = SubmitField('Create Account')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('Username already taken. Please choose another.')

    def validate_promo_code(self, promo_code):
        valid_code = current_app.config.get('SIGNUP_PROMO_CODE', '')
        if promo_code.data.strip().upper() != valid_code.upper():
            raise ValidationError('Invalid promo code.')


class LoginForm(FlaskForm):
    username = StringField('Username', validators=[
        DataRequired()
    ])
    password = PasswordField('Password', validators=[
        DataRequired()
    ])
    remember = BooleanField('Remember me')
    submit = SubmitField('Log In')

class BusyHoursForm(FlaskForm):
    submit = SubmitField('Save My Schedule')


class TaskForm(FlaskForm):
    title = StringField('Task Title', validators=[
        DataRequired(),
        Length(min=1, max=200)
    ])
    description = TextAreaField('Description', validators=[Optional()])
    urgency = SelectField('Urgency', choices=[
        ('1', 'Low'),
        ('2', 'Moderate'),
        ('3', 'High'),
        ('4', 'Critical')
    ], validators=[DataRequired()])
    importance = SelectField('Importance', choices=[
        ('1', 'Low'),
        ('2', 'Moderate'),
        ('3', 'High'),
        ('4', 'Critical')
    ], validators=[DataRequired()])
    estimated_hours = FloatField('Estimated Hours', validators=[
        DataRequired(),
        NumberRange(min=0.5, max=200, message='Enter between 0.5 and 200 hours')
    ])
    deadline = DateField('Deadline', validators=[Optional()], format='%Y-%m-%d')
    is_recurring = BooleanField('Recurring Task')
    recurrence_type = SelectField('Repeat Every', choices=[
        ('', 'Select...'),
        ('daily', 'Day'),
        ('weekly', 'Week')
    ], validators=[Optional()])
    preferred_time = TimeField('Preferred Time (for recurring tasks)',
        validators=[Optional()], format='%H:%M')
    preferred_day = SelectField('Repeat on Day (weekly only)', choices=[
        ('', 'Select day...'),
        ('0', 'Monday'), ('1', 'Tuesday'), ('2', 'Wednesday'),
        ('3', 'Thursday'), ('4', 'Friday'),
        ('5', 'Saturday'), ('6', 'Sunday'),
    ], validators=[Optional()])
    submit = SubmitField('Add Task')