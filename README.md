# YouTube Frontend Web Server

![YouTube Frontend Web Server Logo](ytb-logo.png)

A Python-based web server that creates a new frontend for YouTube.

## Overview

This project creates a web server that allows users to interact with YouTube 
data using a custom frontend. The server uses the `yt-dlp` library to fetch 
YouTube data and the `http.server` library to create a web server.

## Features

* Fetches YouTube data using `yt-dlp`
* Creates a custom frontend for YouTube data
* Supports various types of YouTube data, including videos, playlists, and channels
* Has a simple and intuitive interface for navigating and searching YouTube data
* Can be easily customized and extended using HTML, CSS, and JavaScript

When u click into a thumbnail the link is coppied into clipboard so u can open 
and play the video using **mpv** or download the video using 'yt-dlp'.

## Installation and Setup
To run the server, simply execute the `server.py` file:
```bash
python3 server.py
```

The server will start listening on port 8080 by default. You can change the 
port number by modifying the port variable in the server.py file.

## Usage

To use the server, open a web browser and navigate to http://localhost:8080. 

You can then interact with the server using the following URLs:

*  /: Displays the main page of the server
*  /style.css: Displays the CSS file for the server
*  /ytb-logo.png: Displays the logo image for the server
*  /copy/<video_id>: Copies the video ID and other metadata to the clipboard
*  /channel/<channel_id>: Displays the channel data for the specified channel
*  /playlist/<playlist_id>: Displays the playlist data for the specified playlist
*  /search?q=<query>: Searches for videos, playlists, or channels using the specified query

## Contributing

Pull requests are welcome! If you'd like to contribute to the project, please fork the repository and submit a pull request. Be sure to follow the standard professional guidelines for pull requests.
License

This project is licensed under the MIT License. See the LICENSE file for details.
Acknowledgments

*  yt-dlp for providing the library for fetching YouTube data
*  http.server for providing the library for creating a web server
*  Arch Linux for providing the base system and tools
