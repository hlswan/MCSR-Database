/**
 * Initializes the MCSR Performance Graph
 * @param {Array} wrData - The world record progression data from Flask
 */
Chart.defaults.font.family = "'Share Tech Mono', monospace";
Chart.defaults.color = "#5a7a5a";
Chart.defaults.font.size = 16;
function initMCSRGraph(wrData) {
    const ctx = document.getElementById('mcsrChart').getContext('2d');

    // Clone data so we don't mutate original
    const extendedData = [...wrData];

    if (extendedData.length > 0) {
        const lastPoint = extendedData[extendedData.length - 1];

        extendedData.push({
            date: new Date().toISOString(), // today
            time: lastPoint.time,
            runner: lastPoint.runner // optional, for tooltip consistency
        });
    }

    const datasets = [{
        label: 'World Record Progression',
        data: extendedData.map(d => ({ x: d.date, y: d.time })),
        borderColor: '#4ade80',
        backgroundColor: 'rgba(74, 222, 128, 0.1)',
        stepped: true,
        borderWidth: 2,
        pointRadius: (ctx) => {
            return ctx.dataIndex === extendedData.length - 1 ? 0 : 4;
        },
        pointHoverRadius: 6
    }];

    const chart = new Chart(ctx, {
        type: 'line',
        data: { datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    type: 'time',
                    time: {
                        unit: 'year',
                        displayFormats: { year: 'yyyy' }
                    },
                    max: new Date(),
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    title: { display: true, text: 'Date' }
                },
                y: {
                    reverse: false, // Lower time is better
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    title: { display: true, text: 'Time (M:SS.sss)' },
                    ticks: {
                        callback: (value) => {
                            let totalSeconds = Math.floor(value / 1000);
                            let m = Math.floor(totalSeconds / 60);
                            let s = totalSeconds % 60;
                            return `${m}:${s.toString().padStart(2, '0')}`;
                        }
                    }
                }
            },
            plugins: {
                tooltip: {
                    callbacks: {
                        // This part controls the BOLD text at the top of the tooltip
                        title: function(context) {
                            // context[0].raw.x is the date string
                            const dateFull = context[0].raw.x;
                            // Split by space to remove "00:00:00" or "12:00 AM"
                            return dateFull.split(' ')[0];
                        },
                        // This part controls the runner name and time
                        label: function(context) {
                            const point = wrData[context.dataIndex];
                            let totalSeconds = Math.floor(point.time / 1000);
                            let m = Math.floor(totalSeconds / 60);
                            let s = totalSeconds % 60;
                            let sFixed = s.toString().padStart(2, '0');
                            let ms = (point.time % 1000).toString().padStart(3, '0');

                            return ` ${point.runner}: ${m}:${sFixed}.${ms}`;
                        }
                    }
                }
            }
        }
    });

    // Handle Resize
    window.addEventListener('resize', () => chart.resize());

    return chart;
}