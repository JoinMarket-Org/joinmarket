#!/bin/bash
set -e
clear

#check for root
if [ "$(id -u)" = "0" ]; then
echo "You should not run as root;
you will be prompted for the admin password when needed."
read -p "Press ENTER to exit the script, and run again, not as root."
exit 0
fi

echo "This script will install JOINMARKET on your computer.
You are strongly recommended to run it with a local Bitcoin Core
instance for extra privacy. See the Joinmarket wiki for details."
read -p "Press ENTER to continue."

echo "Will now update apt"
#sudo apt-get update
clear

echo "Will now install dependencies"
sudo apt-get install -y build-essential
sudo apt-get install -y automake
#required for secp256k1
sudo apt-get install -y libgmp-dev
pip install pexpect
pip install cffi

echo "will now get libsodium and secp256k1 and compile."
git clone git://github.com/jedisct1/libsodium.git
cd libsodium
git checkout tags/1.0.3
./autogen.sh
./configure
make check
sudo make install
cd ..

git clone git://github.com/bitcoin/secp256k1.git
cd secp256k1
./autogen.sh
./configure --enable-module-ecdh --enable-module-schnorr --enable-module-recovery
make
./tests
sudo make install
cd ..
sudo ldconfig
#set up python bindings
cd lib/bitcoin
python build.py
python noncefunc_build.py
cd ../..
#tests
python lib/enc_wrapper.py
