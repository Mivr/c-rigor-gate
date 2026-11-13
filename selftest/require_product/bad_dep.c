/* Depends on another gate target (gate//ctest:perf): not allowed, only gate//rt:require is. */
int bad_dep(int x) {
    return x + 1;
}
