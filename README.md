# awesome-py-libp2p-examples

A curated collection of **practical, minimal, and well-documented examples** built using
[py-libp2p](https://github.com/libp2p/py-libp2p).

This repository is intended to help contributors, learners, and builders:
- Understand py-libp2p core modules by *building*
- Explore real-world usage patterns
- Create reusable reference implementations
- Improve onboarding for new contributors

---

## 🎯 Purpose

py-libp2p is a powerful but modular P2P networking stack.  
The best way to understand it is by **writing small, focused examples** that exercise specific parts of the system.

This repo focuses on:
- Learning by doing
- Isolated, easy-to-run examples
- Clear explanations over completeness
- Community-driven contributions

---

## 🧩 What goes here?

Each example should:
- Live in its **own subdirectory**
- Focus on **one core concept or module**
- Be minimal, readable, and documented

Example categories include (but are not limited to):

- 🔌 Transports (TCP, WebSocket, WebRTC)
- 🔐 Security protocols
- 🔀 Stream multiplexers
- 🌐 Peer discovery & dialing
- 🔁 Connection lifecycle
- 🧪 Interop & testing demos
- 🧵 Async / Trio integration patterns
- 🖥️ CLI-based tools using py-libp2p

---

## 📁 Repository Structure

```text
awesome-py-libp2p-examples/
│
├── webrtc-basic/
│   ├── README.md
│   └── example.py
│
├── tcp-echo/
│   ├── README.md
│   └── echo.py
│
├── discovery-mdns/
│   ├── README.md
│   └── main.py
│
└── README.md
