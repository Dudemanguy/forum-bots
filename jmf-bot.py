import argparse
import getpass
import http.cookiejar
import mechanize
import os
import random
import re
import socket
import sys
import time
from bs4 import BeautifulSoup

class IRC:
 
    irc = socket.socket()
  
    def __init__(self):
        # Define the socket
        self.irc = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def channel_join(self, channel):
        self.irc.send(bytes("JOIN " + channel + "\n", "UTF-8"))
 
    def send(self, channel, msg):
        # Transfer data
        self.irc.send(bytes("PRIVMSG " + channel + " :" + msg + "\n", "UTF-8"))
 
    def server_connect(self, server, port, botnick):
        # Connect to the server
        print("Connecting to: " + server)
        self.irc.connect((server, port))

        # Perform user authentication
        self.irc.send(bytes("USER " + botnick + " " + botnick +" " + botnick + " :python\n", "UTF-8"))
        self.irc.send(bytes("NICK " + botnick + "\n", "UTF-8"))
        time.sleep(5)

    def get_response(self):
        time.sleep(1)
        # Get the response
        resp = self.irc.recv(2040).decode("UTF-8")
 
        return resp

    def reply_pong(self, resp):
        if resp.find('PING') != -1:                      
            for i in range(len(resp.split())):
                if resp.split()[i] == "PING":
                    self.irc.send(bytes('PONG '+resp.split()[i+1]+'\r\n', "UTF-8"))

def get_new_html():
    searchurl = "https://japanesemetalforum.com/search.php?action=getdaily"
    posts = br.open(searchurl).read()
    soup = BeautifulSoup(posts, "html.parser")
    return soup

def update_info(soup):
    poster = []
    thread = []
    time = []
    url = []
    poster_names = soup.find_all("span", class_="smalltext")
    thread_names = soup.find_all("a", {"id" : re.compile("tid_.*")})
    for i in range(len(poster_names)-1, -1, -1):
        if poster_names[i].strong != None and poster_names[i].span != None:
            if str(poster_names[i].a).find("search") > -1:
                continue
            poster.append(poster_names[i].strong.contents[0])
    for i in range(len(poster_names)-1, -1, -1):
        if poster_names[i].span != None and str(poster_names[i].a).find("search") == -1:
            time.append(poster_names[i].contents[2][2:])
    for i in range(len(poster_names)-1, -1, -1):
        if poster_names[i].span != None and str(poster_names[i].a).find("search") == -1:
            ending = poster_names[i].a['href']
            url.append(baseurl+ending)
    for i in range(len(thread_names)-1, -1, -1):
        thread.append(thread_names[i].contents[0])
    full = []
    for i in range(len(poster)):
        full.append([poster[i], thread[i], time[i], url[i]])
    return full

def exists_in_old(item, old_full):
    for i in range(0, len(old_full)):
        if item == old_full[i]:
            return True
    return False

baseurl = "https://japanesemetalforum.com/"
loginurl = "https://japanesemetalforum.com/member.php?action=login"
cj = http.cookiejar.CookieJar()

br = mechanize.Browser()
br.set_cookiejar(cj)
br.set_handle_equiv(True)
br.set_handle_gzip(True)
br.set_handle_redirect(True)
br.set_handle_referer(True)
br.set_handle_robots(False)
br.set_handle_refresh(mechanize._http.HTTPRefreshProcessor(), max_time=1)
br.addheaders = [('User-agent', 'Chrome')]

br.open(loginurl)
br.select_form(nr=1)
br.form['username'] = input("Username: ")
br.form['password'] = getpass.getpass("Password: ")
br.submit()

server = "irc.rizon.net"
port = 6667
channel = "#jpmetal"
botnick = "JMF_Bot"
irc = IRC()
irc.server_connect(server, port, botnick)
in_channel = False
old_full = []

while True:
    soup = get_new_html()
    full = update_info(soup)
    text = irc.get_response()
    print(text)
 
    irc.reply_pong(text)
    if not in_channel:
        irc.channel_join(channel)
        in_channel = True

    for i in range(0, len(full)):
        if not exists_in_old(full[i], old_full):
            irc.send(channel, "[JMF_Bot] "+full[i][0]+" made a new post in thread: "+full[i][1]+" ("+full[i][2]+")")
            irc.send(channel, full[i][3])
            time.sleep(1)
    old_full = full
    time.sleep(60)
