#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

// Bionic loads Carbonyl through linker64. For this browser only, resolve the
// executable link to the ELF that owns the Chromium resources.
static ssize_t executable_link(const char *path, char *buffer, size_t size) {
    static const char executable[] =
        "/data/data/com.terminal.nextgen/files/usr/lib/carbonyl/headless_shell";
    const char *name = getprogname();
    if (strcmp(path, "/proc/self/exe") || !name) return -2;
    const char *base = strrchr(name, '/');
    name = base ? base + 1 : name;
    if (strcmp(name, "headless_shell") && strcmp(name, "carbonyl")) return -2;
    if (!size) { errno = EINVAL; return -1; }
    size_t length = sizeof(executable) - 1;
    if (length > size) length = size;
    memcpy(buffer, executable, length);
    return (ssize_t)length;
}

ssize_t readlink(const char *path, char *buffer, size_t size) {
    ssize_t result = executable_link(path, buffer, size);
    if (result != -2) return result;
    ssize_t (*next)(const char *, char *, size_t) = dlsym(RTLD_NEXT, "readlink");
    if (!next) { errno = ENOSYS; return -1; }
    return next(path, buffer, size);
}

ssize_t readlinkat(int directory, const char *path, char *buffer, size_t size) {
    ssize_t result = executable_link(path, buffer, size);
    if (result != -2) return result;
    ssize_t (*next)(int, const char *, char *, size_t) = dlsym(RTLD_NEXT, "readlinkat");
    if (!next) { errno = ENOSYS; return -1; }
    return next(directory, path, buffer, size);
}
