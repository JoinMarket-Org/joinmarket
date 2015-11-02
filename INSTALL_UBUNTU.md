# Installing on Ubuntu\Debian

To to build Joinmarked on Ubuntu or Debian, you will first need to install these dependendencies

  - build-essential
  - python-dev
  - automake
  - libtool
  - git

```m
# apt-get install build-essential python-dev automake libtool git
```

Clone the repository
```m
$ git clone https://github.com/chris-belcher/joinmarket.git ~/joinmarket
$ cd ~/joinmarket
```

Run the install script
```m
$ ./install.sh
```

If built successfully, you should see this text
```m
Encryption test PASSED for case: short ascii
Encryption test PASSED for case: long b64
Encryption test PASSED for case: endless_wittering
Encryption test PASSED for case: 1 char
All test cases passed - encryption and decryption should work correctly.
```

Run this command to set the directory for joinmarket

```m
$ echo "export joinmarket_home=$(pwd)" >> ~/.bashrc
```

Add these lines to your `~/.bashrc` file, underneath `export joinmarket_home ...`
```m
export ptyprocess_root=${joinmarket_home}/deps/build/ptyprocess
export pexpect_root=${joinmarket_home}/deps/build/pexpect
export pycparser_root=${joinmarket_home}/deps/build/pycparser
export cffi_root=${joinmarket_home}/deps/build/cffi
export libsodium_root=${joinmarket_home}/deps/build/libsodium
export secp256k1_root=${joinmarket_home}/deps/build/secp256k1
export PYTHONPATH=${pycparser_root}/lib/python2.7/site-packages:${cffi_root}/lib/python2.7/site-packages/:${pexpect_root}/lib/python2.7/site-packages/:${ptyprocess_root}/lib/python2.7/site-packages:${PYTHONPATH}
export LD_LIBRARY_PATH=${libsodium_root}/lib:${secp256k1_root}/lib:${LD_LIBRARY_PATH}
```

Finally, source the  `~/.bashrc`
```m
$ source ~/.bashrc
```

You should now be able to use joinmarket

# Cleaning up

Navigate to your joinmarket directory
```m
$ cd ${joinmarket_home}
```

Remove all libraries and built files
```m
$ rm -rf ./deps/
$ rm ./lib/bitcoin/_libsecp256k1.*
$ rm ./lib/bitcoin/_noncefunc.*
```

Finally, remove the exported variables from your `~/.bashrc` file.
