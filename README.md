# AMT Quotation

## Project structure

```text
app.py                         Application entry point
backend/
  app.py                       Flask application factory
  config.py                    Project, frontend, and database paths
  database.py                  Database initialization and activity logs
  secret.key                   Existing session signing key
  common/
    auth.py                    Authentication and role checks
    request.py                 Client IP helper
  login/
    routes.py                  Login, logout, profile, password changes
  manager_dashboard/
    routes.py                  Dashboard statistics and user management
  quotation_tool/
    routes.py                  Quotation page, lookup, rates, and cache
    shopify.py                 Shopify lookup and currency services
    search_routes.py           Combined search and Zoho image endpoints
    search_service.py          Zoho and blog search services
frontend/
  login/
    login.html
    login.css
    login.js
  manager_dashboard/
    manager.html
    manager.css
    manager.js
  quotation_tool/
    quotation.html
    quotation.css
    quotation.js
database/
  quotation.db                 Existing users and activity history
```

## Run on Windows

From the project root, use the existing virtual environment:

```powershell
.\.venv\Scripts\python.exe app.py
```

Open <http://127.0.0.1:5062/login>. Stop any previously running instance
with Ctrl+C before starting the restructured app. The URLs `/login`, `/`,
`/manager`, and `/api/...` remain the same. Frontend CSS and JavaScript are
served at `/static/<module>/<filename>`.

For a new environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

The existing database and secret key have been moved, preserving accounts,
passwords, history, and session signing. Back up `database/quotation.db`
and `backend/secret.key` together. The Zoho integration still expects the
existing sibling `Pricing-App` directory next to this project.
