# Copyright (c) 2026 Shubhan Punde · https://github.com/Drakeion2532/doctor-sahyog-health-card · MIT licence · sp2532-114d38316204
from sahyog import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5000)
