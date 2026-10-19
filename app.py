"""Start the AMT Quotation app from the project root."""
from backend.app import create_app

app = create_app()

if __name__ == '__main__':
    from backend.common.live_rates import start_scheduler
    start_scheduler()
    print('AMT Quotation Web App running on http://127.0.0.1:5062')
    app.run(host='0.0.0.0', port=5062, debug=False, threaded=True)
