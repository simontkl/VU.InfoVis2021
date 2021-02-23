# InfoVis 2021

Note: All setup instructions are only tested under Linux and macOS.

#### Prerequisites

Clone this GitHub repository and navigate to the directory:
```bash
git clone git@github.com:hkstm/VU.InfoVis2021.git
git clone https://github.com/hkstm/VU.InfoVis2021.git # if you use HTTPS instead of SSH
cd VU.InfoVis2021
```

If not yet installed, get the `yarn` package manager:
```bash
sudo npm install --global yarn
```

#### Setup

After you installed the prerequisites, start the frontend with 
```bash
# assuming you have cloned the repo
# and you are in the project root folder as described in the Prerequisites
cd frontend
yarn install
yarn start
```
This will run the app in the development mode with automatic reloads if you make changes.
Open [http://localhost:3000](http://localhost:3000) to view it in the browser.

To build the app for final deployment, run:
```
yarn build
```

This builds and optimizes the app for production to the `build` folder.

#### Documentation

To learn React, check out the [React documentation](https://reactjs.org/).