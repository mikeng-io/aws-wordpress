/* E5 instrument: what a stat() costs on files the client did NOT just create.
 *
 * bench.c creates its tree and stats it seconds later, so on NFS it times the
 * client's attribute cache, not the server (E2, results/E2/20261015T000959Z-85382cc).
 * agebench never creates anything. The tree is seeded by the HOST, through a
 * mount that is unmounted before this runs, so every mount agebench touches meets
 * the files as a client that has never seen them.
 *
 * bench.c is deliberately untouched: E2 and E3's instrument stays byte-identical.
 * The tree shape and file sizes are bench.c's, and every stat/read here checks the
 * size it finds against bench.c's file_size() formula - so a seeder that drifted
 * from the formula fails the run instead of silently measuring a different tree.
 *
 * Timing primitive is bench.c's: clock_gettime(CLOCK_MONOTONIC) around each call.
 *
 *   agebench pass  <dir> <op> <cohort> [passes]
 *       op = stat | enoent | open_read. One timed pass (or `passes` of them) over
 *       the tree in fixed order. One line per op: "cohort,op,seq,ns".
 *
 *   agebench serve <dir> <delta_s> <warmup_s> <measure_s> <cohort> <outprefix> <raw_every>
 *       A web tier after a deploy: open_read every file once (opcache's compile),
 *       then one request every delta_s on absolute deadlines, each stat()ing all
 *       1,000 files and all 1,000 missing names. Writes:
 *         <outprefix>.req.csv      one line per request: per-op sparse histograms
 *         <outprefix>.raw.csv      every op of every raw_every-th request
 *         <outprefix>.compile.csv  the compile step, one line per open_read
 *         <outprefix>.mountstats.warm / .end   /proc/self/mountstats at the
 *                                  warm-up boundary and at the end
 *
 * Any op that returns the wrong answer - a stat that fails on a seeded file, a
 * missing name that exists, a size that is not the formula's - exits non-zero.
 * A wrong answer is never a latency.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define DIRS 20
#define FILES_PER_DIR 50
#define N (DIRS * FILES_PER_DIR)
#define MAX_PATH 512
/* Histogram: 20 bins per decade from 100 ns. Bin -1 is < 100 ns, bin 140 is >= 1 s.
 * 12% bin width; the hit/miss split this experiment reads is ~2 decades wide. */
#define BINS_PER_DECADE 20
#define BIN_MIN (-1)
#define BIN_MAX 140
#define NBINS (BIN_MAX - BIN_MIN + 1)

static char files[N][MAX_PATH];
static char missing[N][MAX_PATH];
static size_t sizes[N];
static char *buf;

static long ns_between(const struct timespec *a, const struct timespec *b) {
    return (b->tv_sec - a->tv_sec) * 1000000000L + (b->tv_nsec - a->tv_nsec);
}

/* bench.c's formula, verbatim. */
static size_t file_size(int dir_i, int file_i) {
    unsigned h = (unsigned)(dir_i * 9973 + file_i * 7919);
    return 2048 + (h % (51200 - 2048));
}

static void build_paths(const char *root) {
    for (int d = 0; d < DIRS; d++)
        for (int f = 0; f < FILES_PER_DIR; f++) {
            int i = d * FILES_PER_DIR + f;
            snprintf(files[i], MAX_PATH, "%s/plugin-%03d/includes/class-%03d.php", root, d, f);
            snprintf(missing[i], MAX_PATH, "%s/plugin-%03d/includes/missing-%03d.php", root, d, f);
            sizes[i] = file_size(d, f);
        }
}

static void die(const char *what, const char *path, const char *why) {
    fprintf(stderr, "agebench: WRONG ANSWER on %s %s: %s\n", what, path, why);
    exit(2);
}

/* Each timed op. Verification happens AFTER the second clock read, so it is never
 * inside the timed interval. */
static long timed_stat(int i) {
    struct timespec t0, t1;
    struct stat st;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    int rc = stat(files[i], &st);
    clock_gettime(CLOCK_MONOTONIC, &t1);
    if (rc != 0) die("stat", files[i], strerror(errno));
    if ((size_t)st.st_size != sizes[i]) die("stat", files[i], "size is not bench.c's file_size()");
    return ns_between(&t0, &t1);
}

static long timed_enoent(int i) {
    struct timespec t0, t1;
    struct stat st;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    int rc = stat(missing[i], &st);
    int e = errno;
    clock_gettime(CLOCK_MONOTONIC, &t1);
    if (rc == 0) die("enoent", missing[i], "name exists");
    if (e != ENOENT) die("enoent", missing[i], strerror(e));
    return ns_between(&t0, &t1);
}

static long timed_open_read(int i) {
    struct timespec t0, t1;
    size_t total = 0;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    int fd = open(files[i], O_RDONLY);
    if (fd < 0) { int e = errno; die("open", files[i], strerror(e)); }
    ssize_t r;
    do { r = read(fd, buf, 65536); if (r > 0) total += (size_t)r; } while (r > 0);
    close(fd);
    clock_gettime(CLOCK_MONOTONIC, &t1);
    if (r < 0) die("read", files[i], "read failed");
    if (total != sizes[i]) die("read", files[i], "byte count is not bench.c's file_size()");
    return ns_between(&t0, &t1);
}

static int bin_of(long ns) {
    if (ns < 100) return BIN_MIN;
    int b = (int)floor(BINS_PER_DECADE * log10((double)ns / 100.0));
    return b > BIN_MAX ? BIN_MAX : b;
}

static int cmd_pass(int argc, char **argv) {
    if (argc < 5) { fprintf(stderr, "usage: agebench pass <dir> <op> <cohort> [passes]\n"); return 64; }
    const char *op = argv[3], *cohort = argv[4];
    int passes = argc > 5 ? atoi(argv[5]) : 1;
    long (*fn)(int);
    if (!strcmp(op, "stat")) fn = timed_stat;
    else if (!strcmp(op, "enoent")) fn = timed_enoent;
    else if (!strcmp(op, "open_read")) fn = timed_open_read;
    else { fprintf(stderr, "agebench: unknown op %s\n", op); return 64; }
    if (passes < 1) { fprintf(stderr, "agebench: passes must be >= 1\n"); return 64; }
    build_paths(argv[2]);
    for (int p = 0; p < passes; p++)
        for (int i = 0; i < N; i++)
            printf("%s,%s,%d,%ld\n", cohort, op, p * N + i, fn(i));
    return 0;
}

static int copy_file(const char *src, const char *dst) {
    FILE *in = fopen(src, "r"), *out = fopen(dst, "w");
    if (!in || !out) { if (in) fclose(in); if (out) fclose(out); return -1; }
    char b[65536];
    size_t n;
    while ((n = fread(b, 1, sizeof b, in)) > 0) fwrite(b, 1, n, out);
    fclose(in);
    return fclose(out);
}

static void write_bins(FILE *f, const long *h) {
    int first = 1;
    for (int b = 0; b < NBINS; b++)
        if (h[b]) { fprintf(f, "%s%d:%ld", first ? "" : "|", b + BIN_MIN, h[b]); first = 0; }
}

static void add_ns(struct timespec *t, long ns) {
    t->tv_sec += ns / 1000000000L;
    t->tv_nsec += ns % 1000000000L;
    if (t->tv_nsec >= 1000000000L) { t->tv_sec++; t->tv_nsec -= 1000000000L; }
}

static int cmd_serve(int argc, char **argv) {
    if (argc < 9) {
        fprintf(stderr, "usage: agebench serve <dir> <delta_s> <warmup_s> <measure_s> <cohort> <outprefix> <raw_every>\n");
        return 64;
    }
    double delta = atof(argv[3]), warmup = atof(argv[4]), measure = atof(argv[5]);
    const char *cohort = argv[6], *prefix = argv[7];
    int raw_every = atoi(argv[8]);
    if (delta <= 0 || warmup < 0 || measure <= 0 || raw_every < 1) {
        fprintf(stderr, "agebench: bad serve arguments\n");
        return 64;
    }
    long delta_ns = (long)llround(delta * 1e9);
    long n_warm = lround(warmup / delta), n_meas = lround(measure / delta);
    build_paths(argv[2]);

    char path[MAX_PATH];
    FILE *req, *raw, *comp;
    snprintf(path, sizeof path, "%s.req.csv", prefix);
    req = fopen(path, "w");
    snprintf(path, sizeof path, "%s.raw.csv", prefix);
    raw = fopen(path, "w");
    snprintf(path, sizeof path, "%s.compile.csv", prefix);
    comp = fopen(path, "w");
    if (!req || !raw || !comp) { perror("agebench: open output"); return 1; }

    /* Compile: the first request after a deploy. On OpenZFS this is when read
     * delegations are granted, which is what prediction 6 is about. */
    for (int i = 0; i < N; i++) fprintf(comp, "%s,open_read,%d,%ld\n", cohort, i, timed_open_read(i));
    fclose(comp);

    fprintf(req, "# cohort=%s delta_ns=%ld warm_requests=%ld measured_requests=%ld raw_every=%d bins_per_decade=%d bin0_ns=100\n",
            cohort, delta_ns, n_warm, n_meas, raw_every, BINS_PER_DECADE);
    fprintf(req, "k,phase,lateness_ns,stat_sum_ns,enoent_sum_ns,stat_bins,enoent_bins\n");

    struct timespec deadline, start;
    clock_gettime(CLOCK_MONOTONIC, &deadline);
    long hs[NBINS], he[NBINS];
    for (long k = 0; k < n_warm + n_meas; k++) {
        if (k == n_warm) {
            /* Boundary: counters are read BEFORE the first measured request. */
            snprintf(path, sizeof path, "%s.mountstats.warm", prefix);
            if (copy_file("/proc/self/mountstats", path) != 0) { perror("agebench: mountstats"); return 1; }
        }
        clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &deadline, NULL);
        clock_gettime(CLOCK_MONOTONIC, &start);
        long late = ns_between(&deadline, &start);
        memset(hs, 0, sizeof hs);
        memset(he, 0, sizeof he);
        long sum_s = 0, sum_e = 0;
        int keep_raw = (k % raw_every) == 0;
        for (int i = 0; i < N; i++) {
            long a = timed_stat(i), b = timed_enoent(i);
            sum_s += a; sum_e += b;
            hs[bin_of(a) - BIN_MIN]++;
            he[bin_of(b) - BIN_MIN]++;
            if (keep_raw) fprintf(raw, "%ld,stat,%d,%ld\n%ld,enoent,%d,%ld\n", k, i, a, k, i, b);
        }
        fprintf(req, "%ld,%c,%ld,%ld,%ld,", k, k < n_warm ? 'w' : 'm', late, sum_s, sum_e);
        write_bins(req, hs);
        fputc(',', req);
        write_bins(req, he);
        fputc('\n', req);
        add_ns(&deadline, delta_ns);
    }
    snprintf(path, sizeof path, "%s.mountstats.end", prefix);
    if (copy_file("/proc/self/mountstats", path) != 0) { perror("agebench: mountstats"); return 1; }
    fclose(req);
    fclose(raw);
    return 0;
}

int main(int argc, char **argv) {
    buf = malloc(65536);
    if (argc >= 2 && !strcmp(argv[1], "pass")) return cmd_pass(argc, argv);
    if (argc >= 2 && !strcmp(argv[1], "serve")) return cmd_serve(argc, argv);
    fprintf(stderr, "usage: agebench pass|serve ...\n");
    return 64;
}
