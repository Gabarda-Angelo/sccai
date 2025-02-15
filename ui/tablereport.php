<?php
// tablereport.php
include_once 'connectdb.php';
session_start();

if (!isset($_SESSION['email']) || $_SESSION['role'] === 'Cashier') { 
  echo "<script>
          alert('Sorry, you can\'t access this. Please contact the Admin.');
          window.location.href = '../index.php';
        </script>"; 
  exit;
}

// Use the appropriate header file based on user role
include_once ($_SESSION['role'] == 'Cashier') ? 'headeruser.php' : 'header.php';

// -------------------------------------------------------------------------
// Determine the default "from" date as the earliest invoice date.
$stmt = $pdo->query("SELECT MIN(order_date) AS min_date FROM invoices");
$row = $stmt->fetch(PDO::FETCH_OBJ);
$date_from_default = $row->min_date ? $row->min_date . ' 00:00:00' : date('Y-m-d 00:00:00');

// Set date range based on POST or default values.
$date_from = isset($_POST['date_1']) ? $_POST['date_1'] : $date_from_default;
$date_to   = isset($_POST['date_2']) ? $_POST['date_2'] : date('Y-m-d H:i:s');
?>
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Sales Report</title>
  <!-- Bootstrap CSS -->
  <link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css">
  <!-- Tempus Dominus (Datetimepicker) CSS -->
  <link rel="stylesheet" href="../plugins/tempusdominus-bootstrap-4/css/tempusdominus-bootstrap-4.min.css">
  <!-- Daterangepicker CSS (if needed) -->
  <link rel="stylesheet" href="../plugins/daterangepicker/daterangepicker.css">
  <!-- DataTables Bootstrap 4 CSS -->
  <link rel="stylesheet" href="../plugins/datatables-bs4/css/dataTables.bootstrap4.min.css">
  <link rel="stylesheet" href="../plugins/datatables-responsive/css/responsive.bootstrap4.min.css">
  <link rel="stylesheet" href="../plugins/datatables-buttons/css/buttons.bootstrap4.min.css">
  <!-- Optional: Font Awesome for icons -->
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.4/css/all.min.css" />
  <style>
    /* Some spacing between cards */
    .card { margin-bottom: 20px; }
  </style>
</head>
<body>
<div class="content-wrapper">
  <!-- Page Header -->
  <div class="container-fluid">
    <div class="row mt-4">
      <div class="col-12">
        <h1 class="mb-4">Sales Report</h1>
      </div>
    </div>

    <!-- Row 1: Filter Form and Overview Stats -->
    <div class="row">
      <!-- Date Filter Form Card -->
      <div class="col-md-4">
        <div class="card">
          <div class="card-header bg-primary text-white">
            <h5 class="m-0">Filter by Date</h5>
          </div>
          <div class="card-body">
            <form method="post">
              <div class="form-group">
                <label for="date_1">From:</label>
                <div class="input-group date" id="date_1" data-target-input="nearest">
                  <input type="text" name="date_1" class="form-control datetimepicker-input" data-target="#date_1" value="<?= htmlspecialchars($date_from) ?>" />
                  <div class="input-group-append" data-target="#date_1" data-toggle="datetimepicker">
                    <div class="input-group-text"><i class="fa fa-calendar"></i></div>
                  </div>
                </div>
              </div>
              <div class="form-group">
                <label for="date_2">To:</label>
                <div class="input-group date" id="date_2" data-target-input="nearest">
                  <input type="text" name="date_2" class="form-control datetimepicker-input" data-target="#date_2" value="<?= htmlspecialchars($date_to) ?>" />
                  <div class="input-group-append" data-target="#date_2" data-toggle="datetimepicker">
                    <div class="input-group-text"><i class="fa fa-calendar"></i></div>
                  </div>
                </div>
              </div>
              <button type="submit" class="btn btn-warning btn-block" name="btnfilter">Filter</button>
            </form>
          </div>
        </div>
      </div>
      
      <!-- Overview Stats Card -->
      <div class="col-md-8">
        <div class="card">
          <div class="card-header bg-success text-white">
            <h5 class="m-0">Overview (Period: <?= htmlspecialchars($date_from) ?> - <?= htmlspecialchars($date_to) ?>)</h5>
          </div>
          <div class="card-body">
            <?php
            // Query for overview statistics.
            $stmt = $pdo->prepare("
                SELECT COUNT(invoice_id) AS total_invoices,
                       SUM(subtotal) AS total_subtotal,
                       SUM(total) AS total_grand
                FROM invoices
                WHERE CONCAT(order_date, ' ', order_time) BETWEEN :date_from AND :date_to
            ");
            $stmt->execute([
                ':date_from' => $date_from,
                ':date_to'   => $date_to
            ]);
            $stats = $stmt->fetch(PDO::FETCH_OBJ);
            $total_invoices = $stats->total_invoices;
            $total_subtotal = $stats->total_subtotal;
            $aov = ($total_invoices > 0) ? $total_subtotal / $total_invoices : 0;
            
            // Total Discount Calculation.
            $stmtDiscount = $pdo->prepare("
                SELECT SUM((discount/100) * subtotal) AS total_discount
                FROM invoices
                WHERE CONCAT(order_date, ' ', order_time) BETWEEN :date_from AND :date_to
            ");
            $stmtDiscount->execute([
                ':date_from' => $date_from,
                ':date_to'   => $date_to
            ]);
            $discountRow = $stmtDiscount->fetch(PDO::FETCH_OBJ);
            $total_discount = $discountRow->total_discount;
            
            // Static counts.
            $stmt = $pdo->prepare("SELECT COUNT(product_id) AS pname FROM products");
            $stmt->execute();
            $row = $stmt->fetch(PDO::FETCH_OBJ);
            $total_product = $row->pname;
            
            $stmt = $pdo->prepare("SELECT COUNT(category_name) AS cate FROM categories");
            $stmt->execute();
            $row = $stmt->fetch(PDO::FETCH_OBJ);
            $total_category = $row->cate;
            
            // Expenses and Profit.
            $stmtExpenses = $pdo->prepare("
                SELECT SUM(id.quantity * p.purchase_price) AS total_expenses
                FROM invoice_details id
                JOIN products p ON id.product_id = p.product_id
                JOIN invoices i ON id.invoice_id = i.invoice_id
                WHERE CONCAT(i.order_date, ' ', i.order_time) BETWEEN :date_from AND :date_to
            ");
            $stmtExpenses->execute([
                ':date_from' => $date_from,
                ':date_to'   => $date_to
            ]);
            $expensesRow = $stmtExpenses->fetch(PDO::FETCH_OBJ);
            $total_expenses = $expensesRow->total_expenses ? $expensesRow->total_expenses : 0;
            $profit = $total_subtotal - $total_expenses;
            ?>
            <!-- Row 1: General Metrics -->
            <div class="row text-center">
              <div class="col-sm-6 col-lg-3 mb-3">
                <div class="border p-2 rounded">
                  <h6>Average Sales Value</h6>
                  <h4>₱<?= number_format($aov, 2) ?></h4>
                </div>
              </div>
              <div class="col-sm-6 col-lg-3 mb-3">
                <div class="border p-2 rounded">
                  <h6>Total Discount</h6>
                  <h4>₱<?= number_format($total_discount, 2) ?></h4>
                </div>
              </div>
              <div class="col-sm-6 col-lg-3 mb-3">
                <div class="border p-2 rounded">
                  <h6>Total Products</h6>
                  <h4><?= htmlspecialchars($total_product) ?></h4>
                </div>
              </div>
              <div class="col-sm-6 col-lg-3 mb-3">
                <div class="border p-2 rounded">
                  <h6>Total Categories</h6>
                  <h4><?= htmlspecialchars($total_category) ?></h4>
                </div>
              </div>
            </div>
            <!-- Row 2: Sales Summary -->
            <div class="row text-center">
              <div class="col-md-4 mb-3">
                <div class="border p-2 rounded bg-light">
                  <h6>Total Invoices</h6>
                  <h4><?= number_format($total_invoices) ?></h4>
                </div>
              </div>
              <div class="col-md-4 mb-3">
                <div class="border p-2 rounded bg-light">
                  <h6>Total Revenue</h6>
                  <h4>₱<?= number_format($total_subtotal, 2) ?></h4>
                </div>
              </div>
              <div class="col-md-4 mb-3">
                <div class="border p-2 rounded bg-light">
                  <h6>Net Total</h6>
                  <h4>₱<?= number_format($stats->total_grand, 2) ?></h4>
                </div>
              </div>
            </div>
            <!-- Row 3: Cost & Profit -->
            <div class="row text-center">
              <div class="col-md-6 mb-3">
                <div class="border p-2 rounded bg-light">
                  <h6>Base Cost</h6>
                  <h4>₱<?= number_format($total_expenses, 2) ?></h4>
                </div>
              </div>
              <div class="col-md-6 mb-3">
                <div class="border p-2 rounded bg-light">
                  <h6>Profit</h6>
                  <h4>₱<?= number_format($profit, 2) ?></h4>
                </div>
              </div>
            </div>
          </div><!-- /.card-body -->
        </div><!-- /.card -->
      </div>
    </div> <!-- End Row 1 -->

    <!-- Row 2: Additional Sales Data -->
    <div class="row">
      <!-- Best Selling Product Card -->
      <div class="col-md-6">
        <div class="card">
          <div class="card-header bg-danger text-white">
            <h5 class="m-0">Best Selling Product(Period: <?= htmlspecialchars($date_from) ?> - <?= htmlspecialchars($date_to) ?>)</h5>
          </div>
          <div class="card-body">
            <table class="table table-striped table-hover" id="table_bestsellingproduct">
              <thead>
                <tr>
                  <th>Product ID</th>
                  <th>Product Name</th>
                  <th>QTY</th>
                  <th>Rate</th>
                  <th>Total</th>
                </tr>
              </thead>
              <tbody>
                <?php
                $stmt = $pdo->prepare("
                    SELECT id.product_id, p.product_name, SUM(id.quantity) AS q,
                           MAX(id.unit_price) AS rate, SUM(id.total_price) AS total
                    FROM invoice_details id
                    JOIN products p ON id.product_id = p.product_id
                    JOIN invoices i ON id.invoice_id = i.invoice_id
                    WHERE CONCAT(i.order_date, ' ', i.order_time) BETWEEN :date_from AND :date_to
                    GROUP BY id.product_id
                    ORDER BY SUM(id.quantity) DESC
                    LIMIT 10
                ");
                $stmt->execute([
                    ':date_from' => $date_from,
                    ':date_to'   => $date_to
                ]);
                while ($row = $stmt->fetch(PDO::FETCH_OBJ)) {
                  echo '
                    <tr>
                      <td>' . htmlspecialchars($row->product_id) . '</td>
                      <td><span class="badge badge-dark">' . htmlspecialchars($row->product_name) . '</span></td>
                      <td><span class="badge badge-success">' . htmlspecialchars($row->q) . '</span></td>
                      <td><span class="badge badge-primary">' . htmlspecialchars($row->rate) . '</span></td>
                      <td><span class="badge badge-danger">' . htmlspecialchars($row->total) . '</span></td>
                    </tr>
                  ';
                }
                ?>
              </tbody>
            </table>
          </div>
        </div>
      </div>
      
      <!-- Recent Invoices Card -->
      <div class="col-md-6">
        <div class="card">
          <div class="card-header bg-info text-white">
            <h5 class="m-0">Recent Invoices (Period: <?= htmlspecialchars($date_from) ?> - <?= htmlspecialchars($date_to) ?>)</h5>
          </div>
          <div class="card-body">
            <table class="table table-striped table-hover" id="table_recentorder">
              <thead>
                <tr>
                  <th>Invoice ID</th>
                  <th>Invoice Date</th>
                  <th>Total</th>
                  <th>Payment Type</th>
                </tr>
              </thead>
              <tbody>
                <?php
                $stmt = $pdo->prepare("
                    SELECT *, CONCAT(order_date, ' ', order_time) AS order_datetime
                    FROM invoices
                    WHERE CONCAT(order_date, ' ', order_time) BETWEEN :date_from AND :date_to
                    ORDER BY invoice_id DESC
                    LIMIT 30
                ");
                $stmt->execute([
                    ':date_from' => $date_from,
                    ':date_to'   => $date_to
                ]);
                while ($row = $stmt->fetch(PDO::FETCH_OBJ)) {
                  echo '
                    <tr>
                      <td><a href="editorderpos.php?id=' . htmlspecialchars($row->invoice_id) . '">' . htmlspecialchars($row->invoice_id) . '</a></td>
                      <td><span class="badge badge-dark">' . htmlspecialchars($row->order_datetime) . '</span></td>
                      <td><span class="badge badge-danger">₱' . htmlspecialchars(number_format($row->total, 2)) . '</span></td>';
                  if ($row->payment_type == "Cash") {
                    echo '<td><span class="badge badge-warning">' . htmlspecialchars($row->payment_type) . '</span></td>';
                  } else if ($row->payment_type == "Card") {
                    echo '<td><span class="badge badge-success">' . htmlspecialchars($row->payment_type) . '</span></td>';
                  } else {
                    echo '<td><span class="badge badge-danger">' . htmlspecialchars($row->payment_type) . '</span></td>';
                  }
                  echo '</tr>';
                }
                ?>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div> <!-- End Row 2 -->

    <!-- Row 3: Sales Details -->
    <div class="row">
      <div class="col-12">
        <div class="card card-warning">
          <div class="card-header">
          <h5 class="m-0 text-white">Sales Details (Period: <?= htmlspecialchars($date_from) ?> - <?= htmlspecialchars($date_to) ?>)</h5>

          </div>
          <div class="card-body">
            <?php
            try {
                $invoices = $pdo->prepare("
                    SELECT invoice_id,
                           CONCAT(order_date, ' ', order_time) AS order_datetime,
                           subtotal,
                           discount,
                           total,
                           paid,
                           due,
                           payment_type
                    FROM invoices
                    WHERE CONCAT(order_date, ' ', order_time) BETWEEN :from_date AND :to_date
                    ORDER BY invoice_id DESC
                ");
                $invoices->execute([
                    ':from_date' => $date_from,
                    ':to_date'   => $date_to
                ]);
            ?>
            <table class="table table-striped" id="table_report">
              <thead class="thead-dark">
                <tr>
                  <th>Invoice ID</th>
                  <th>Invoice Date</th>
                  <th>Subtotal</th>
                  <th>Discount</th>
                  <th>Total</th>
                  <th>Paid</th>
                  <th>Due</th>
                  <th>Payment Method</th>
                </tr>
              </thead>
              <tbody>
                <?php
                while ($invoice = $invoices->fetch(PDO::FETCH_OBJ)) {
                    $payment_badge = 'primary';
                    if ($invoice->payment_type == 'Card') {
                        $payment_badge = 'success';
                    } else if ($invoice->payment_type == 'Check') {
                        $payment_badge = 'warning';
                    }
                    echo '
                      <tr>
                        <td>' . htmlspecialchars($invoice->invoice_id) . '</td>
                        <td>' . htmlspecialchars($invoice->order_datetime) . '</td>
                        <td>₱' . number_format($invoice->subtotal, 2) . '</td>
                        <td>' . number_format($invoice->discount, 2) . '%</td>
                        <td>₱' . number_format($invoice->total, 2) . '</td>
                        <td>₱' . number_format($invoice->paid, 2) . '</td>
                        <td>₱' . number_format($invoice->due, 2) . '</td>
                        <td><span class="badge badge-' . $payment_badge . '">' . htmlspecialchars($invoice->payment_type) . '</span></td>
                      </tr>
                    ';
                }
                ?>
              </tbody>
            </table>
            <?php
            } catch(PDOException $e) {
                echo '<div class="alert alert-danger">Database Error: ' . htmlspecialchars($e->getMessage()) . '</div>';
            }
            ?>
          </div>
        </div>
      </div>
    </div> <!-- End Row 3 -->

  </div><!-- /.container-fluid -->
</div><!-- /.content-wrapper -->

<?php include_once "footer.php"; ?>

<!-- JavaScript Dependencies -->
<script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
<script src="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/js/bootstrap.bundle.min.js"></script>
<script src="../plugins/moment/moment.min.js"></script>
<script src="../plugins/tempusdominus-bootstrap-4/js/tempusdominus-bootstrap-4.min.js"></script>
<!-- DataTables JS (Bootstrap 4 integration) -->
<script src="../plugins/datatables/jquery.dataTables.min.js"></script>
<script src="../plugins/datatables-bs4/js/dataTables.bootstrap4.min.js"></script>
<script src="../plugins/datatables-responsive/js/dataTables.responsive.min.js"></script>
<script src="../plugins/datatables-responsive/js/responsive.bootstrap4.min.js"></script>
<script src="../plugins/datatables-buttons/js/dataTables.buttons.min.js"></script>
<script src="../plugins/datatables-buttons/js/buttons.bootstrap4.min.js"></script> 
<!-- SweetAlert2 -->
<script src="plugins/sweetalert2/sweetalert2.min.js"></script>
<script>
$(document).ready(function() {
    // Initialize datetimepickers with format settings.
    $('#date_1').datetimepicker({ format: 'YYYY-MM-DD HH:mm:ss' });
    $('#date_2').datetimepicker({ format: 'YYYY-MM-DD HH:mm:ss' });
    
    // Initialize DataTables.
    $('#table_bestsellingproduct').DataTable({
         responsive: true,
         order: [[0, 'asc']]
    });
    $('#table_recentorder').DataTable({
         responsive: true,
         order: [[0, 'desc']]
    });
    $('#table_report').DataTable({
         responsive: true,
         order: [[0, 'desc']]
    });
    
    // Initialize tooltips if needed.
    $('[data-toggle="tooltip"]').tooltip();
});
</script>  
 

<?php if (isset($_SESSION['status'])): ?>
    <script>
        $(function() {
            const Toast = Swal.mixin({
                toast: true,
                position: 'top center',
                showConfirmButton: false,
                timer: 3000
            });

            Toast.fire({
                icon: '<?= $_SESSION['status_code'] ?>',
                title: '<?= $_SESSION['status'] ?>'
            });
           
        });
    </script>
<?php
    unset($_SESSION['status']);
    unset($_SESSION['status_code']);
endif; ?>
</body>
</html>
