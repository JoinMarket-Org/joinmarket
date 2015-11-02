#!/bin/sh
set -e

joinmarket_home="$(dirname $(readlink -f "$0"))"

git submodule init
git submodule update

# Downloading and unpacking cffi
rm -f ${joinmarket_home}/deps/cffi-1.3.0.tar.gz
wget -t 5 https://pypi.python.org/packages/source/c/cffi/cffi-1.3.0.tar.gz -O ${joinmarket_home}/deps/cffi-1.3.0.tar.gz
md5sum -c <<E
a40ed8c8ac653c8fc7d5603711b06eaf  ./deps/cffi-1.3.0.tar.gz
E
tar -C ./deps -xzf ${joinmarket_home}/deps/cffi-1.3.0.tar.gz

# Downloading and unpacking libgmp
rm -f ${joinmarket_home}/deps/gmp-6.1.0.tar.bz2
wget -t 5 https://gmplib.org/download/gmp/gmp-6.1.0.tar.bz2 -O ${joinmarket_home}/deps/gmp-6.1.0.tar.bz2
bunzip2 -f ${joinmarket_home}/deps/gmp-6.1.0.tar.bz2
sha256sum -c <<E
7afbeccd5b248a4996ad9ff08f66dc46d30fa53364ba436dfb86d67fc4a35848  ./deps/gmp-6.1.0.tar
E
tar -C ./deps -xf ${joinmarket_home}/deps/gmp-6.1.0.tar

# Building libffi

libffi_root=${joinmarket_home}/deps/build/libffi
cd ${joinmarket_home}/deps/libffi/
./configure --prefix=${libffi_root}
make
make install


# Building ptyprocess

ptyprocess_root=${joinmarket_home}/deps/build/ptyprocess
cd ${joinmarket_home}/deps/ptyprocess
python setup.py build
python setup.py install --prefix=${ptyprocess_root}


# Building pexpect

pexpect_root=${joinmarket_home}/deps/build/pexpect
cd ${joinmarket_home}/deps/pexpect
export PYTHONPATH=${ptyprocess_root}/lib/python2.7/site-packages/:${PYTHONPATH}
python setup.py build
python setup.py install --prefix=${pexpect_root}


# Building pycparser

pycparser_root=${joinmarket_home}/deps/build/pycparser
cd ${joinmarket_home}/deps/pycparser
python setup.py build
python setup.py install --prefix=${pycparser_root}


# Building cffi

cffi_root=${joinmarket_home}/deps/build/cffi
cd ${joinmarket_home}/deps/cffi-1.3.0

export C_INCLUDE_PATH=${libffi_root}/lib/libffi-3.0.13/include:${C_INCLUDE_PATH}
export LIBRARY_PATH=${libffi_root}/lib:${LIBRARY_PATH}

python setup_base.py build
python setup_base.py install --prefix=${cffi_root}
ln -sf ${joinmarket_home}/deps/cffi-1.3.0/cffi/_cffi_include.h ${cffi_root}/lib/python2.7/site-packages/cffi/
ln -sf ${joinmarket_home}/deps/cffi-1.3.0/cffi/parse_c_type.h ${cffi_root}/lib/python2.7/site-packages/cffi/

# Building libsodium

libsodium_root=${joinmarket_home}/deps/build/libsodium
cd ${joinmarket_home}/deps/libsodium
./autogen.sh
./configure --prefix=${libsodium_root}
make
make install


# Building gmp

gmp_root=${joinmarket_home}/deps/build/gmp
cd ${joinmarket_home}/deps/gmp-6.1.0
./configure --prefix=${gmp_root}
make
make check
make install


# Building secp256k1

secp256k1_root=${joinmarket_home}/deps/build/secp256k1
cd ${joinmarket_home}/deps/secp256k1

./autogen.sh
export C_INCLUDE_PATH=${gmp_root}/include/:${C_INCLUDE_PATH}
export LIBRARY_PATH=${gmp_root}/lib:${LIBRARY_PATH}
./configure --enable-module-ecdh --enable-module-schnorr --enable-module-recovery --prefix=${secp256k1_root}
make
./tests
make install


# Building joinmarket 

cd ${joinmarket_home}/lib/bitcoin

export C_INCLUDE_PATH=${libsodium_root}/include:${secp256k1_root}/include:${C_INCLUDE_PATH}
export LIBRARY_PATH=${libsodiom_root}/lib:${secp256k1_root}/lib:${LIBRARY_PATH}
export PYTHONPATH=${pycparser_root}/lib/python2.7/site-packages:${cffi_root}/lib/python2.7/site-packages/:${pexpect_root}/lib/python2.7/site-packages/:${ptyprocess_root}/lib/python2.7/site-packages/:${PYTHONPATH}
python build.py
python noncefunc_build.py

cd ${joinmarket_home}/lib
export LD_LIBRARY_PATH=${libsodium_root}/lib:${secp256k1_root}/lib:${LD_LIBRARY_PATH}
python enc_wrapper.py
