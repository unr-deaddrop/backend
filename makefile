run:
	python3 manage.py runserver 0.0.0.0:8000

run_noreload:
	python3 manage.py runserver 0.0.0.0:8000 --noreload

# We manually make migrations for django_celery_results before invoking the
# generalized `makemigrations` command. Since we add a field to the models
# in django_celery_results, that generates a corresponding migration file.
#
# However, because it's stored in site-packages, that migration won't exist
# until runtime. At the same time, however, if we commit the initial migration,
# it will depend on that file existing. If we then try and move this into a
# docker container, the initial migration will refer to the django_celery_results
# migration that *should* exist, but doesn't.
#
# In turn, we manually invoke this first.
migrate:
	python3 manage.py makemigrations django_celery_results
	python3 manage.py makemigrations
	python3 manage.py migrate

test:
	python3 manage.py test

shell:
	python3 manage.py shell

cshell:
	python3 manage.py shell < shellTest.py

fake:
	python3 manage.py migrate --fake backend

flush:
	python3 manage.py flush --no-input

purge: flush
	rm db.sqlite3 || true
	rm -r packages || true
	rm -r media || true
	make migrate

admin:
	python3 manage.py createsuperuser

# Never fail
admin_headless:
	python3 manage.py createsuperuser --noinput || true

dep:
	pip3 install -r requirements.txt 

startdocker:
	sudo dockerd

rmdocker:
	rm -rf  ~/.docker

rmdockerconfig:
	rm ~/.docker/config.json

docker_image:
	docker build -t deaddrop/backend:1.0 .

docker_run-%:
	docker run -p 8000:8000 $*

docker_compose_up:
	docker-compose up -d --build

docker_compose_down:
	docker-compose down

docker_compose_down_all:
	docker-compose down --rmi all --volumes

docker_compose_stop:
	docker-compose stop

all:
	make migrate run