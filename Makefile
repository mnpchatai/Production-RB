# คำสั่งที่ใช้บ่อย — ทุกคำสั่งรันจากรากโปรเจกต์
SHELL := /bin/bash
PY := backend/.venv/bin/python
PIP := backend/.venv/bin/pip

.PHONY: help setup migrate seed run test lint front-install front-dev front-build up down reset

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "};{printf "  \033[36m%-14s\033[0m %s\n",$$1,$$2}'

setup: ## สร้าง virtualenv และติดตั้ง dependency ของ backend
	python3 -m venv backend/.venv
	$(PIP) install --upgrade pip
	$(PIP) install "django>=5.0,<6" "djangorestframework>=3.15" "psycopg[binary]>=3.1" \
		"django-cors-headers>=4.4" "gunicorn>=22" "pytest>=8" "pytest-django>=4.8"

migrate: ## รัน migration ทั้งหมด
	cd backend && ../$(PY) manage.py migrate

seed: ## สร้างข้อมูลตัวอย่างพร้อมสต็อกและใบสั่งงาน
	cd backend && ../$(PY) manage.py seed_demo --with-stock --with-orders

run: ## รัน backend ที่ http://127.0.0.1:8000
	cd backend && ../$(PY) manage.py runserver 0.0.0.0:8000

test: ## รันเทสต์ทั้งหมด (ต้องมี PostgreSQL จริง)
	cd backend && DJANGO_SETTINGS_MODULE=config.settings.test ../$(PY) -m pytest

lint: ## ตรวจ config ของ Django และหา migration ที่ยังไม่ได้สร้าง
	cd backend && ../$(PY) manage.py check
	cd backend && ../$(PY) manage.py makemigrations --check --dry-run

front-install: ## ติดตั้ง dependency ของหน้าจอ
	cd frontend && npm install

front-dev: ## รันหน้าจอหน้างานที่ http://127.0.0.1:5173
	cd frontend && npm run dev

front-build: ## build หน้าจอสำหรับขึ้นระบบจริง
	cd frontend && npm run typecheck && npm run build

up: ## รันทั้งระบบด้วย docker compose
	docker compose up --build

down: ## หยุดและลบ container
	docker compose down

reset: ## ล้างฐานข้อมูลแล้วเริ่มใหม่ (ข้อมูลหายหมด)
	docker compose down -v
