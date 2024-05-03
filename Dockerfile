FROM python:3.11.4-bookworm

WORKDIR /app

# prevent .pyc files
ENV PYTHONDONTWRITEBYTECODE 1
# ensure output ios sent directly to terminal without buffering
ENV PYTHONUNBUFFERED 1

# Update package lists and install required packages
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsm6 \
    libxext6

# Install the docker client (used to spin up agent containers)
COPY install-docker.sh .
RUN chmod +x install-docker.sh
RUN ./install-docker.sh

# Install pip requirements
COPY requirements.txt .
RUN pip3 install --upgrade pip
RUN pip3 install -r requirements.txt

# Set up the Postgres entrypoint script
COPY entrypoint.sh .
RUN sed -i 's/\r$//g' entrypoint.sh
RUN chmod +x entrypoint.sh

# Install nc so the script actually works
RUN apt install netcat-openbsd

# Copy everything else
COPY . .

ENV PORT=8000
EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]