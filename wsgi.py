from app import app

# PythonAnywhere expects "application"; Render's existing wsgi:app still works.
application = app

