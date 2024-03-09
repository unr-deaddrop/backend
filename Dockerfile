FROM python:3.11.4-bookworm

WORKDIR /app

# prevent .pyc files
ENV PYTHONDONTWRITEBYTECODE 1
# ensure output ios sent directly to terminal without buffering
ENV PYTHONUNBUFFERED 1

COPY . .

# Install the docker client (used to spin up agent containers)
RUN chmod +x install-docker.sh
RUN ./install-docker.sh

# Install pip requirements
RUN pip3 install --upgrade pip
RUN pip3 install -r requirements.txt

ENV PORT=8000
EXPOSE 8000