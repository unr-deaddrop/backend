run:
	python3 manage.py runserver

migrate:
	python3 manage.py migrate

all:
	make migrate run