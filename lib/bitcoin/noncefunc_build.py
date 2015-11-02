from cffi import FFI

ffi = FFI()
ffi.cdef('static int nonce_function_rand(unsigned char *nonce32,const unsigned char *msg32,const unsigned char *key32,const unsigned char *algo16,void *data,unsigned int attempt);')


ffi.set_source("_noncefunc",
"""
static int nonce_function_rand(unsigned char *nonce32,
const unsigned char *msg32,
const unsigned char *key32,
const unsigned char *algo16,
void *data,
unsigned int attempt)
{
memcpy(nonce32,data,32);
return 1;
}
""")

if __name__ == '__main__':
    ffi.compile()
