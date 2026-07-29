const button = document.getElementById("analyzeBtn");

button.addEventListener("click", () => {

    const progress = document.querySelector(".progress-fill");

    const status = document.getElementById("statusText");

    let width = 0;

    const messages = [

        "Checking SEO...",

        "Checking Security...",

        "Checking Accessibility...",

        "Checking Performance...",

        "Generating AI Report..."

    ];

    let index = 0;

    const timer = setInterval(() => {

        width += 20;

        progress.style.width = width + "%";

        status.innerHTML = messages[index];

        index++;

        if(width >= 100){

            clearInterval(timer);

            status.innerHTML="Analysis Complete ✔";

            document.getElementById("seoScore").innerHTML="89%";

            document.getElementById("securityScore").innerHTML="91%";

            document.getElementById("accessibilityScore").innerHTML="84%";

            document.getElementById("performanceScore").innerHTML="93%";

        }

    },1000);

});