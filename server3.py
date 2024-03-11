# This is server code to send video and audio frames over UDP/TCP

from concurrent.futures import ThreadPoolExecutor
import cv2
import imutils
import socket
import numpy as np
import time
import base64
import threading
import wave
import pyaudio
import pickle
import struct
import sys
import queue
import os
NUM_CLIENTS = 2

q = queue.Queue(maxsize=10)

filename = 'videoplayback.mp4'
command = "ffmpeg -i {} -ab 160k -ac 2 -ar 44100 -vn {}".format(
    filename, 'temp.wav')
os.system(command)

BUFF_SIZE = 65536
server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, BUFF_SIZE)
host_name = socket.gethostname()
host_ip = socket.gethostbyname(host_name)
print(host_ip)
port = 9688
socket_address = (host_ip, port)
server_socket.bind(socket_address)
print('Listening at:', socket_address)

vid = cv2.VideoCapture(filename)
FPS = vid.get(cv2.CAP_PROP_FPS)
global TS
TS = (0.5/FPS)
BREAK = False
print('FPS:', FPS, TS)
totalNoFrames = int(vid.get(cv2.CAP_PROP_FRAME_COUNT))
durationInSeconds = float(totalNoFrames) / float(FPS)
d = vid.get(cv2.CAP_PROP_POS_MSEC)
print(durationInSeconds, d)


def video_stream_gen():

    WIDTH = 400
    while (vid.isOpened()):
        try:
            _, frame = vid.read()
            frame = imutils.resize(frame, width=WIDTH)
            q.put(frame)
        except:
            os._exit(1)
    print('Player closed')
    BREAK = True
    vid.release()


def video_stream():
    global TS
    fps, st, frames_to_count, cnt = (0, 0, 1, 0)
    cv2.namedWindow('TRANSMITTING VIDEO')
    cv2.moveWindow('TRANSMITTING VIDEO', 10, 30)
    client_sockets = []  # list of connected client sockets
    while True:
        # accept new connections
        while len(client_sockets) < NUM_CLIENTS:
            try:
                client_socket, client_addr = server_socket.accept()
                print('Accepted connection from', client_addr)
                client_sockets.append(client_socket)
            except socket.error:
                pass

        # send frames to all connected clients
        WIDTH = 400
        while True:
            frame = q.get()
            encoded, buffer = cv2.imencode(
                '.jpeg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            message = base64.b64encode(buffer)
            for client_socket in client_sockets:
                try:
                    client_socket.sendall(message)
                except socket.error:
                    client_sockets.remove(client_socket)
            frame = cv2.putText(frame, 'FPS: '+str(round(fps, 1)),
                                (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            if cnt == frames_to_count:
                try:
                    fps = (frames_to_count/(time.time()-st))
                    st = time.time()
                    cnt = 0
                    if fps > FPS:
                        TS += 0.001
                    elif fps < FPS:
                        TS -= 0.001
                    else:
                        pass
                except:
                    pass


CHUNK = 1024


def send_audio(client_socket):
    while True:
        try:
            message = client_socket.recv(8)
            length = struct.unpack("Q", message)[0]
            data = b""

            while len(data) < length:
                packet = client_socket.recv(length - len(data))
                if not packet:
                    break
                data += packet

            if not data:
                break

            frames = pickle.loads(data)
            stream.write(frames)
        except Exception as e:
            print('Error receiving audio from client:', e)
            break

    client_socket.close()


def audio_stream():
    wf = wave.open("temp.wav", 'rb')
    p = pyaudio.PyAudio()
    stream = p.open(format=p.get_format_from_width(wf.getsampwidth()),
                    channels=wf.getnchannels(),
                    rate=wf.getframerate(),
                    input=True,
                    frames_per_buffer=CHUNK)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host_ip, (port-1)))
        s.listen()

        print('server listening at', (host_ip, (port-1)))

        while True:
            client_sockets = []
            client_addresses = []

            # Wait for clients to connect
            for i in range(NUM_CLIENTS):
                client_socket, addr = s.accept()
                print('Accepted connection from', addr)
                client_sockets.append(client_socket)
                client_addresses.append(addr)

            # Start a new thread for each client
            threads = []
            for i in range(NUM_CLIENTS):
                t = threading.Thread(
                    target=send_audio, args=(client_sockets[i],))
                t.start()
                threads.append(t)

            # Send audio frames to all clients in a loop
            while True:
                data = wf.readframes(CHUNK)
                if not data:
                    break

                try:
                    a = pickle.dumps(data)
                    message = struct.pack("Q", len(a)) + a

                    for client_socket in client_sockets:
                        client_socket.sendall(message)
                except Exception as e:
                    print('Error sending audio to clients:', e)

            # Wait for all threads to finish
            for t in threads:
                t.join()

            # Close all client sockets
            for client_socket in client_sockets:
                client_socket.close()


with ThreadPoolExecutor(max_workers=3) as executor:
    executor.submit(audio_stream)
    executor.submit(video_stream_gen)
    executor.submit(video_stream)
