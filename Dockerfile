from python:3.9.15
workdir /app
add . .
RUN pip3 install -r requirements.txt
CMD ['python3', '/app/main.py']