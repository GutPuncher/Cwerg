-- prime number sieve
module sieve:

import test

global SIZE uint = 1000000

global EXPECTED uint = 148932

-- The array is initialized to all true because the explicit
-- value for the first element is replicated for the
-- subsequent unspecified ones.
-- 
-- index i reprents number 3 + 2 * i
global! is_prime = array(SIZE, bool)[true]

-- the actual sieve function
fun sieve() uint:
    let! count uint = 0
    for i = 0, SIZE, 1:
        if is_prime[i]:
            set count += 1
            let p uint = 3 + i + i
            for k = i + p, SIZE, p:
                set is_prime[k] = false
    return count

@cdecl fun main(argc s32, argv ptr(ptr(u8))) s32:
    test::AssertEq#(sieve(), EXPECTED)
    test::Success#()
    return 0

