<?php
// graphreport.php
error_reporting(E_ALL);
ini_set('display_errors', 1);
include_once 'connectdb.php';
session_start();

// Set the default timezone to Philippines time
date_default_timezone_set('Asia/Manila');

if (!isset($_SESSION['email']) || $_SESSION['role'] === 'Cashier') {
    echo "<script>
            alert('Sorry, you can\'t access this. Please contact the Admin.');
            window.location.href = '../index.php';
          </script>";
    exit;
}

// --- Determine Date/Time Range ---
// Expecting the date/time picker to return strings like "02/13/2025 06:00 AM"
if ($_SERVER['REQUEST_METHOD'] === 'POST' && !empty($_POST['date_1']) && !empty($_POST['date_2'])) {
    // Parse the incoming date/time strings using the expected format.
    $d1 = DateTime::createFromFormat('m/d/Y h:i A', $_POST['date_1']);
    $d2 = DateTime::createFromFormat('m/d/Y h:i A', $_POST['date_2']);
    if ($d1 && $d2) {
        // We'll use the full datetime values for filtering.
        $startDateTime = $d1->format('Y-m-d H:i:s');
        $endDateTime   = $d2->format('Y-m-d H:i:s');
        // For display in the picker, use the same m/d/Y format.
        $displayStartDate = $d1->format('m/d/Y');
        $displayEndDate   = $d2->format('m/d/Y');
    } else {
        // If parsing fails, fall back (not recommended)
        $displayStartDate = $_POST['date_1'];
        $displayEndDate   = $_POST['date_2'];
        $startDateTime = $displayStartDate . " 00:00:00";
        $endDateTime   = $displayEndDate . " 23:59:59";
    }
} else {
    // If no filter submitted, get the earliest created_at from invoices as default start
    $minQuery  = $pdo->query("SELECT MIN(created_at) AS first_datetime FROM invoices");
    $minResult = $minQuery->fetch(PDO::FETCH_ASSOC);
    if (!empty($minResult['first_datetime'])) {
        $displayStartDate = date("m/d/Y", strtotime($minResult['first_datetime']));
    } else {
        $displayStartDate = date('m/d/Y');
    }
    $displayEndDate = date('m/d/Y');
    // Convert the display dates back to Y-m-d for filtering
    $startDateTime  = date('Y-m-d', strtotime($displayStartDate)) . " 00:00:00";
    $endDateTime    = date('Y-m-d', strtotime($displayEndDate)) . " 23:59:59";
}

// --- Decide Grouping: Hourly if same day; Daily if multiple days ---
$groupByField = "";
$orderByField = "";
if ($displayStartDate === $displayEndDate) {
    // For a single day, group by hour.
    $groupByField = "DATE_FORMAT(created_at, '%H:00')"; // e.g. "06:00", "07:00"
    $orderByField = "DATE_FORMAT(created_at, '%H')";
} else {
    // For multiple days, group by day.
    $groupByField = "DATE(created_at)";
    $orderByField = "DATE(created_at)";
}

// Include the proper header based on the role
if ($_SESSION['role'] == "Admin" || $_SESSION['role'] == "Owner") {
    include_once 'header.php';
} else {
    include_once 'headeruser.php';
}
?>
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Sales Analytics Dashboard</title>
    <!-- Include Font Awesome for calendar icons -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.3/css/all.min.css" />
    <!-- Include Tempus Dominus and Daterangepicker CSS -->
    <link rel="stylesheet" href="../plugins/tempusdominus-bootstrap-4/css/tempusdominus-bootstrap-4.min.css">
    <link rel="stylesheet" href="../plugins/daterangepicker/daterangepicker.css">
    <!-- Load jQuery, Bootstrap, Moment.js, Tempus Dominus, Daterangepicker, and Chart.js -->
    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@4.6.2/dist/js/bootstrap.bundle.min.js"></script>
    <script src="../plugins/moment/moment.min.js"></script>
    <script src="../plugins/tempusdominus-bootstrap-4/js/tempusdominus-bootstrap-4.min.js"></script>
    <script src="../plugins/daterangepicker/daterangepicker.js"></script>
    <script src="../plugins/chart.js/Chart.min.js"></script>
</head>
<body>
<div class="content-wrapper">
  <!-- Content Header -->
  <div class="content-header">
    <div class="container-fluid">
      <div class="row mb-2">
        <div class="col-sm-6">
          <h1 class="m-0">Sales Analytics Dashboard</h1>
        </div>
      </div>
    </div>
  </div>
  <!-- /.content-header -->

  <!-- Main content -->
  <div class="content">
    <div class="container-fluid">

      <!-- Date Range Filter Form -->
      <div class="row">
        <div class="col-lg-12">
          <form method="post" action="">
            <div class="card card-primary card-outline">
              <div class="card-header">
                <h5 class="m-0">Date/Time Range: <?= htmlspecialchars($displayStartDate) ?> – <?= htmlspecialchars($displayEndDate) ?></h5>
              </div>
              <div class="card-body">
                <div class="row">
                  <!-- Start Date/Time Picker -->
                  <div class="col-md-5">
                    <div class="form-group">
                      <div class="input-group date" id="date_1" data-target-input="nearest">
                        <input type="text" name="date_1" class="form-control datetimepicker-input" data-target="#date_1" value="<?= htmlspecialchars($displayStartDate) ?> 06:00 AM" placeholder="Start Date/Time" />
                        <div class="input-group-append" data-target="#date_1" data-toggle="datetimepicker">
                          <div class="input-group-text"><i class="fa fa-calendar"></i></div>
                        </div>
                      </div>
                    </div>
                  </div>
                  <!-- End Date/Time Picker -->
                  <div class="col-md-5">
                    <div class="form-group">
                      <div class="input-group date" id="date_2" data-target-input="nearest">
                        <input type="text" name="date_2" class="form-control datetimepicker-input" data-target="#date_2" value="<?= htmlspecialchars($displayEndDate) ?> 06:00 PM" placeholder="End Date/Time" />
                        <div class="input-group-append" data-target="#date_2" data-toggle="datetimepicker">
                          <div class="input-group-text"><i class="fa fa-calendar"></i></div>
                        </div>
                      </div>
                    </div>
                  </div>
                  <!-- Filter Button -->
                  <div class="col-md-2">
                    <button type="submit" class="btn btn-warning btn-block" name="btnfilter">Filter Results</button>
                  </div>
                </div>
              </div>
            </div>
          </form>
        </div>
      </div>
      <!-- End of Date/Time Filter Form -->

      <?php
      // --- Earning Data using created_at ---
      $ttl = [];
      $labelArr = [];
      $earningQuery = $pdo->prepare("SELECT $groupByField AS label, SUM(total) AS total 
                                     FROM invoices 
                                     WHERE created_at BETWEEN :start AND :end 
                                     GROUP BY $groupByField
                                     ORDER BY $orderByField ASC");
      $earningQuery->execute([':start' => $startDateTime, ':end' => $endDateTime]);
      while ($row = $earningQuery->fetch(PDO::FETCH_ASSOC)) {
          $ttl[] = $row['total'];
          $labelArr[] = $row['label'];
      }

      // --- Average Order Value (AOV) Data using created_at ---
      $aovData = [];
      $aovQuery = $pdo->prepare("SELECT $groupByField AS label, AVG(total) AS aov 
                                     FROM invoices 
                                     WHERE created_at BETWEEN :start AND :end 
                                     GROUP BY $groupByField
                                     ORDER BY $orderByField ASC");
      $aovQuery->execute([':start' => $startDateTime, ':end' => $endDateTime]);
      while ($row = $aovQuery->fetch(PDO::FETCH_ASSOC)) {
          $aovData['labels'][] = $row['label'];
          $aovData['aov'][]    = $row['aov'];
      }

      // --- Product Performance Data (overall, no time grouping) ---
      $productData = [];
      $productQuery = $pdo->prepare("SELECT p.product_name, SUM(d.quantity) AS total_qty 
                                     FROM invoice_details d
                                     INNER JOIN products p ON d.product_id = p.product_id
                                     INNER JOIN invoices i ON d.invoice_id = i.invoice_id
                                     WHERE i.created_at BETWEEN :start AND :end 
                                     GROUP BY d.product_id
                                     ORDER BY total_qty DESC");
      $productQuery->execute([':start' => $startDateTime, ':end' => $endDateTime]);
      while ($row = $productQuery->fetch(PDO::FETCH_ASSOC)) {
          $productData['products'][] = $row['product_name'];
          $productData['quantities'][] = $row['total_qty'];
      }
      ?>
      
      <!-- Earning Chart Card -->
      <div class="row">
        <div class="col-lg-12">
          <div class="card card-danger card-outline">
            <div class="card-header">
              <h5 class="m-0">Earnings (<?= htmlspecialchars($labelArr[0] ?? '') ?> - <?= htmlspecialchars(end($labelArr) ?? '') ?>)</h5>
            </div>
            <div class="card-body">
              <canvas id="earningChart" style="height: 250px"></canvas>
            </div>
          </div>
        </div>
      </div>
      <!-- End of Earning Chart -->

      <!-- AOV & Product Performance Charts -->
      <div class="row">
        <div class="col-lg-12">
          <div class="card card-info card-outline">
            <div class="card-header">
              <h5 class="m-0">Analytics (<?= htmlspecialchars($displayStartDate) ?> to <?= htmlspecialchars($displayEndDate) ?>)</h5>
            </div>
            <div class="card-body">
              <!-- Average Order Value Chart -->
              <div class="mb-5">
                <canvas id="aovChart" height="250"></canvas>
              </div>
              <!-- Product Performance Chart -->
              <div>
                <canvas id="productChart" height="250"></canvas>
              </div>
            </div>
          </div>
        </div>
      </div>
      <!-- End of AOV & Product Performance Charts -->
    </div>
  </div>
</div>

<script>
$(document).ready(function () {
    // Initialize Tempus Dominus date/time pickers
    $('#date_1').datetimepicker({
        format: 'MM/DD/YYYY hh:mm A', // expecting format like "02/13/2025 06:00 AM"
        useCurrent: false,
        icons: {
            time: 'far fa-clock',
            date: 'far fa-calendar',
            up: 'fas fa-arrow-up',
            down: 'fas fa-arrow-down',
            previous: 'fas fa-chevron-left',
            next: 'fas fa-chevron-right',
            today: 'fas fa-calendar-check',
            clear: 'far fa-trash-alt',
            close: 'fas fa-times'
        }
    });
    $('#date_2').datetimepicker({
        format: 'MM/DD/YYYY hh:mm A',
        useCurrent: false,
        icons: {
            time: 'far fa-clock',
            date: 'far fa-calendar',
            up: 'fas fa-arrow-up',
            down: 'fas fa-arrow-down',
            previous: 'fas fa-chevron-left',
            next: 'fas fa-chevron-right',
            today: 'fas fa-calendar-check',
            clear: 'far fa-trash-alt',
            close: 'fas fa-times'
        }
    });
});
</script>

<script>
// Earning Chart (Bar Chart)
const earningCtx = document.getElementById('earningChart').getContext('2d');
new Chart(earningCtx, {
    type: 'bar',
    data: {
        labels: <?php echo json_encode($labelArr); ?>,
        datasets: [{
            label: 'Total Earnings',
            backgroundColor: 'rgb(160,4,4)',
            borderColor: 'rgb(160,4,4)',
            data: <?php echo json_encode($ttl); ?>,
            borderWidth: 1
        }]
    },
    options: {
        scales: { y: { beginAtZero: true } }
    }
});
</script>

<script>
// Average Order Value Chart (Bar Chart)
const aovCtx = document.getElementById('aovChart').getContext('2d');
new Chart(aovCtx, {
    type: 'bar',
    data: {
        labels: <?php echo json_encode($aovData['labels'] ?? []); ?>,
        datasets: [{
            label: 'Average Order Value',
            backgroundColor: 'rgba(60,141,188,0.9)',
            borderColor: 'rgba(60,141,188,0.8)',
            data: <?php echo json_encode($aovData['aov'] ?? []); ?>
        }]
    },
    options: {
        responsive: true,
        plugins: { title: { display: true, text: 'Average Order Value' } },
        scales: { y: { beginAtZero: true, title: { display: true, text: 'AOV (Rs)' } } }
    }
});
</script>

<script>
// Product Performance Chart (Pie Chart)
const productCtx = document.getElementById('productChart').getContext('2d');
const productLabels = <?php echo json_encode($productData['products'] ?? []); ?>;
const productDataValues = <?php echo json_encode($productData['quantities'] ?? []); ?>;
const backgroundColors = [
    'rgba(255, 99, 132, 0.7)',
    'rgba(54, 162, 235, 0.7)',
    'rgba(255, 206, 86, 0.7)',
    'rgba(75, 192, 192, 0.7)',
    'rgba(153, 102, 255, 0.7)',
    'rgba(255, 159, 64, 0.7)'
];
while (backgroundColors.length < productLabels.length) {
    backgroundColors.push('rgba(100, 100, 100, 0.7)');
}
new Chart(productCtx, {
    type: 'pie',
    data: {
        labels: productLabels,
        datasets: [{
            data: productDataValues,
            backgroundColor: backgroundColors.slice(0, productLabels.length)
        }]
    },
    options: {
        responsive: true,
        plugins: { title: { display: true, text: 'Units Sold by Product' } }
    }
});
</script>

<?php include_once "footer.php"; ?>
</body>
</html>
